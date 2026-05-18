"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-18

This baseline mirrors the schema previously created by
``Base.metadata.create_all`` so existing local databases can be stamped
with ``alembic stamp 0001_baseline`` instead of being recreated.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("dedupe_key", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("buyer_name", sa.Text()),
        sa.Column("buyer_tax_id", sa.String(length=64)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cpv_codes", sa.JSON(), nullable=False),
        sa.Column("nuts_codes", sa.JSON(), nullable=False),
        sa.Column("region", sa.String(length=255)),
        sa.Column("country", sa.String(length=2), nullable=False, server_default="ES"),
        sa.Column("procedure_type", sa.String(length=255)),
        sa.Column("contract_type", sa.String(length=255)),
        sa.Column("notice_type", sa.String(length=255)),
        sa.Column("estimated_value", sa.Float()),
        sa.Column("award_value", sa.Float()),
        sa.Column("currency", sa.String(length=8)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("awarded_at", sa.DateTime(timezone=True)),
        sa.Column("winner_name", sa.Text()),
        sa.Column("winner_tax_id", sa.String(length=64)),
        sa.Column("url", sa.Text()),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("quality_issues", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_tenders_source_external"),
        sa.UniqueConstraint("dedupe_key", name="uq_tenders_dedupe_key"),
    )
    op.create_index("ix_tenders_source", "tenders", ["source"])
    op.create_index("ix_tenders_external_id", "tenders", ["external_id"])
    op.create_index("ix_tenders_dedupe_key", "tenders", ["dedupe_key"])
    op.create_index("ix_tenders_status", "tenders", ["status"])
    op.create_index("ix_tenders_region", "tenders", ["region"])
    op.create_index("ix_tenders_procedure_type", "tenders", ["procedure_type"])
    op.create_index("ix_tenders_contract_type", "tenders", ["contract_type"])
    op.create_index("ix_tenders_notice_type", "tenders", ["notice_type"])
    op.create_index("ix_tenders_published_at", "tenders", ["published_at"])
    op.create_index("ix_tenders_deadline_at", "tenders", ["deadline_at"])

    op.create_table(
        "tender_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tender_id",
            sa.String(length=36),
            sa.ForeignKey("tenders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("document_type", sa.String(length=128)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
    )
    op.create_index("ix_tender_documents_tender_id", "tender_documents", ["tender_id"])

    op.create_table(
        "tender_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tender_id",
            sa.String(length=36),
            sa.ForeignKey("tenders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tender_embeddings_tender_id", "tender_embeddings", ["tender_id"])

    op.create_table(
        "daily_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("hour_utc", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_daily_jobs_name"),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("daily_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])

    op.create_table(
        "job_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("job_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tender_id",
            sa.String(length=36),
            sa.ForeignKey("tenders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_results_run_id", "job_results", ["run_id"])
    op.create_index("ix_job_results_tender_id", "job_results", ["tender_id"])


def downgrade() -> None:
    op.drop_table("job_results")
    op.drop_table("job_runs")
    op.drop_table("daily_jobs")
    op.drop_table("tender_embeddings")
    op.drop_table("tender_documents")
    op.drop_table("tenders")
