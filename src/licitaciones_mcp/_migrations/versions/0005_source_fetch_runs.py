"""Source fetch run history.

Revision ID: 0005_source_fetch_runs
Revises: 0004_documents
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_source_fetch_runs"
down_revision: str | None = "0004_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_fetch_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dataset_kind", sa.String(length=64), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_cursor", sa.String(length=255), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tenders_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenders_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenders_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "request_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "result_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.create_index("ix_source_fetch_runs_source", "source_fetch_runs", ["source"])
    op.create_index("ix_source_fetch_runs_operation", "source_fetch_runs", ["operation"])
    op.create_index("ix_source_fetch_runs_status", "source_fetch_runs", ["status"])
    op.create_index("ix_source_fetch_runs_dataset_kind", "source_fetch_runs", ["dataset_kind"])
    op.create_index("ix_source_fetch_runs_year", "source_fetch_runs", ["year"])
    op.create_index("ix_source_fetch_runs_source_cursor", "source_fetch_runs", ["source_cursor"])
    op.create_index("ix_source_fetch_runs_started_at", "source_fetch_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_source_fetch_runs_started_at", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_source_cursor", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_year", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_dataset_kind", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_status", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_operation", table_name="source_fetch_runs")
    op.drop_index("ix_source_fetch_runs_source", table_name="source_fetch_runs")
    op.drop_table("source_fetch_runs")
