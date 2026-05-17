"""Embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """Interface for optional text embedding providers."""

    provider: str
    model: str

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed one or more text inputs."""


class NullEmbedder(Embedder):
    """Disabled embedder used when no provider is configured."""

    provider = "none"
    model = "none"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return no vectors while preserving input cardinality."""

        return [[] for _ in texts]
