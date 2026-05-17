"""OpenAI embedding provider using direct HTTP calls."""

from __future__ import annotations

import httpx

from licitaciones_mcp.embeddings.base import Embedder


class OpenAIEmbedder(Embedder):
    """OpenAI embeddings provider."""

    provider = "openai"

    def __init__(self, api_key: str, *, model: str = "text-embedding-3-small") -> None:
        """Create an OpenAI embedder."""

        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts with the OpenAI embeddings API."""

        if not texts:
            return []
        payload = {"model": self.model, "input": texts}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
