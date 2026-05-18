"""FTS + trigram + pgvector + ingest cursors

Revision ID: 0002_fts_pgvector
Revises: 0001_baseline
Create Date: 2026-05-18

Adds Postgres extensions and indexes required by hybrid search,
plus an ``ingest_cursors`` table for resumable backfills.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_fts_pgvector"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEARCH_VECTOR_EXPR = (
    "to_tsvector('spanish', "
    "coalesce(title, '') || ' ' || "
    "coalesce(summary, '') || ' ' || "
    "coalesce(buyer_name, ''))"
)


def upgrade() -> None:
    """Add extensions, FTS column, trigram indexes, and ingest cursors."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
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

    op.execute(
        "ALTER TABLE tenders ADD COLUMN search_vector tsvector "
        f"GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPR}) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenders_search_vector ON tenders USING GIN (search_vector)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenders_title_trgm "
        "ON tenders USING GIN (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenders_buyer_trgm "
        "ON tenders USING GIN (buyer_name gin_trgm_ops)"
    )

    op.create_table(
        "ingest_cursors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source", "kind", "cursor", name="uq_ingest_cursors_triple"),
    )
    op.create_index("ix_ingest_cursors_source_kind", "ingest_cursors", ["source", "kind"])
    op.create_index("ix_ingest_cursors_status", "ingest_cursors", ["status"])


def downgrade() -> None:
    """Reverse the upgrade."""

    op.drop_index("ix_ingest_cursors_status", table_name="ingest_cursors")
    op.drop_index("ix_ingest_cursors_source_kind", table_name="ingest_cursors")
    op.drop_table("ingest_cursors")

    op.execute("DROP INDEX IF EXISTS idx_tenders_buyer_trgm")
    op.execute("DROP INDEX IF EXISTS idx_tenders_title_trgm")
    op.execute("DROP INDEX IF EXISTS idx_tenders_search_vector")
    op.execute("ALTER TABLE tenders DROP COLUMN IF EXISTS search_vector")
    # Extensions are left in place — other tables may depend on them.
