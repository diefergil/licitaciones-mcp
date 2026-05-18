"""Source ingestor tests."""

from __future__ import annotations

import pytest

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import Tender, TenderSource
from licitaciones_mcp.embeddings.base import Embedder
from licitaciones_mcp.jobs.runner import SourceIngestor


class _MismatchEmbedder(Embedder):
    provider = "test"
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        return [[1.0, 0.0]]


class _FakeDatabase:
    def __init__(self) -> None:
        self.embeddings_called = False

    async def upsert_tenders(self, tenders: list[Tender]) -> list[str]:
        return [f"id-{index}" for index, _tender in enumerate(tenders)]

    async def upsert_embeddings(
        self,
        *,
        provider: str,  # noqa: ARG002
        model: str,  # noqa: ARG002
        items: list[tuple[str, list[float]]],  # noqa: ARG002
    ) -> int:
        self.embeddings_called = True
        return len(items)


@pytest.mark.asyncio
async def test_persist_and_embed_skips_mismatched_vector_counts() -> None:
    database = _FakeDatabase()
    ingestor = SourceIngestor(
        Settings(),
        database,  # type: ignore[arg-type]
        embedder=_MismatchEmbedder(),
    )

    ids = await ingestor._persist_and_embed(
        [
            Tender(source=TenderSource.PLACSP, external_id="1", title="One"),
            Tender(source=TenderSource.PLACSP, external_id="2", title="Two"),
        ]
    )

    assert ids == ["id-0", "id-1"]
    assert database.embeddings_called is False
