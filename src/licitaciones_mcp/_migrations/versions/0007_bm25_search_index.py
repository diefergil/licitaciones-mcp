"""pg_textsearch BM25 ranking index.

Revision ID: 0007_bm25_search_index
Revises: 0006_embedding_vector
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op

revision: str = "0007_bm25_search_index"
down_revision: str | None = "0006_embedding_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the BM25 index required by the BM25 search backend."""

    if _requires_bm25():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
        _create_bm25_index()
        return

    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_textsearch;
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_tenders_bm25_text
                ON tenders USING bm25 ((
                    coalesce(title, '''') || '' '' ||
                    coalesce(summary, '''') || '' '' ||
                    coalesce(buyer_name, '''')
                ))
                WITH (text_config=''spanish'')';
        EXCEPTION
            WHEN undefined_file OR undefined_object OR undefined_function OR feature_not_supported
                OR invalid_parameter_value OR data_exception
                OR object_not_in_prerequisite_state OR insufficient_privilege THEN
                RAISE NOTICE 'pg_textsearch unavailable; explicit FTS backend remains active';
        END
        $$;
        """
    )


def downgrade() -> None:
    """Remove the BM25 index."""

    op.execute("DROP INDEX IF EXISTS idx_tenders_bm25_text")


def _requires_bm25() -> bool:
    settings = context.config.attributes.get("settings")
    return getattr(settings, "search_backend", "bm25") == "bm25"


def _create_bm25_index() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenders_bm25_text
            ON tenders USING bm25 ((
                coalesce(title, '') || ' ' ||
                coalesce(summary, '') || ' ' ||
                coalesce(buyer_name, '')
            ))
            WITH (text_config='spanish')
        """
    )
