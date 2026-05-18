"""Lightweight document downloader using the shared HTTP wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class AsyncDocumentClient(Protocol):
    """Minimal async client interface required for document downloads."""

    async def get(self, url: str, **kwargs: object) -> httpx.Response: ...


@dataclass
class DownloadedDocument:
    """Bytes plus minimal HTTP metadata."""

    url: str
    content: bytes
    content_type: str | None


async def download_document(
    url: str, *, client: AsyncDocumentClient, max_bytes: int = 50 * 1024 * 1024
) -> DownloadedDocument:
    """Download a document, capping the payload size."""

    response = await client.get(url)
    response.raise_for_status()
    payload = response.content
    if len(payload) > max_bytes:
        raise ValueError(f"document too large: {len(payload)} bytes > {max_bytes}")
    return DownloadedDocument(
        url=url,
        content=payload,
        content_type=response.headers.get("content-type"),
    )
