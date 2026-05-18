"""Native pgvector shadow column for embeddings.

Revision ID: 0006_embedding_vector
Revises: 0005_source_fetch_runs
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_embedding_vector"
down_revision: str | None = "0005_source_fetch_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional native vector storage when pgvector is available."""

    op.execute(
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


def downgrade() -> None:
    """Remove the optional native vector storage."""

    op.execute("DROP INDEX IF EXISTS idx_tender_embeddings_embedding_vector_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_tender_embeddings_lookup")
    op.execute("ALTER TABLE tender_embeddings DROP COLUMN IF EXISTS embedding_vector")
