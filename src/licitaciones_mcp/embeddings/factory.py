"""Factory for optional embedding providers."""

from __future__ import annotations

from licitaciones_mcp.config import Settings
from licitaciones_mcp.embeddings.base import Embedder, NullEmbedder
from licitaciones_mcp.embeddings.openai import OpenAIEmbedder


def build_embedder(settings: Settings) -> Embedder:
    """Build the configured embedder or a disabled placeholder."""

    if settings.embeddings_enabled and settings.openai_api_key:
        return OpenAIEmbedder(settings.openai_api_key, model=settings.embeddings_model)
    return NullEmbedder()
