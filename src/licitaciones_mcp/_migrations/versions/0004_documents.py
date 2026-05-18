"""Document extraction columns + FTS index on extracted_text.

Revision ID: 0004_documents
Revises: 0003_scheduler
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_documents"
down_revision: str | None = "0003_scheduler"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tender_documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "tender_documents",
        sa.Column("extracted_sections", sa.JSON(), nullable=True),
    )
    op.add_column("tender_documents", sa.Column("parser_name", sa.String(length=64), nullable=True))
    op.add_column(
        "tender_documents",
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("tender_documents", sa.Column("parse_error", sa.Text(), nullable=True))
    op.execute(
        "CREATE INDEX ix_tender_documents_extracted_text_fts "
        "ON tender_documents USING gin (to_tsvector('spanish', coalesce(extracted_text, '')))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tender_documents_extracted_text_fts")
    op.drop_column("tender_documents", "parse_error")
    op.drop_column("tender_documents", "parsed_at")
    op.drop_column("tender_documents", "parser_name")
    op.drop_column("tender_documents", "extracted_sections")
    op.drop_column("tender_documents", "extracted_text")
