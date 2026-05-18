"""Lightweight document downloader using the shared HTTP wrapper."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

import httpx


class AsyncDocumentClient(Protocol):
    """Minimal async client interface required for document downloads."""

    def stream(
        self,
        method: str,
        url: str,
        **kwargs: object,
    ) -> AbstractAsyncContextManager[httpx.Response]: ...


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

    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > max_bytes:
                raise ValueError(f"document too large: {declared_size} bytes > {max_bytes}")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"document too large: {total} bytes > {max_bytes}")
            chunks.append(chunk)
    return DownloadedDocument(
        url=url,
        content=b"".join(chunks),
        content_type=response.headers.get("content-type"),
    )
