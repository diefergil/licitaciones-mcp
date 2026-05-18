"""Scheduler: cron column on daily_jobs + heartbeats table.

Revision ID: 0003_scheduler
Revises: 0002_fts_pgvector
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_scheduler"
down_revision: str | None = "0002_fts_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("daily_jobs", sa.Column("cron", sa.String(length=128), nullable=True))
    op.create_table(
        "scheduler_heartbeats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column(
            "beat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("jobs_loaded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_scheduler_heartbeats_worker_id",
        "scheduler_heartbeats",
        ["worker_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_heartbeats_worker_id", table_name="scheduler_heartbeats")
    op.drop_table("scheduler_heartbeats")
    op.drop_column("daily_jobs", "cron")
