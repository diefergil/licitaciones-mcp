"""Document download and parser orchestration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from licitaciones_mcp.documents.base import ParsedDocument
from licitaciones_mcp.documents.downloader import download_document
from licitaciones_mcp.documents.processor import process_document


class _FakeClient:
    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        **kwargs: object,  # noqa: ARG002
    ) -> AsyncIterator[httpx.Response]:
        yield httpx.Response(
            200,
            content=b"licitacion document body",
            headers={"content-type": "text/plain"},
            request=httpx.Request(method, url),
        )


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.chunks_read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk


class _ChunkedClient:
    def __init__(self, stream: _ChunkedStream) -> None:
        self._stream = stream

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        **kwargs: object,  # noqa: ARG002
    ) -> AsyncIterator[httpx.Response]:
        yield httpx.Response(
            200,
            stream=self._stream,
            request=httpx.Request(method, url),
        )


class _TextParser:
    name = "text-test"

    def supports(self, *, content_type: str | None, url: str) -> bool:  # noqa: ARG002
        return content_type == "text/plain"

    def parse(self, data: bytes, *, url: str) -> ParsedDocument:  # noqa: ARG002
        text = data.decode("utf-8")
        return ParsedDocument(
            text=text,
            sections=[{"name": "body", "text": text}],
            parser_name=self.name,
        )


class _NoopParser:
    name = "noop"

    def supports(self, *, content_type: str | None, url: str) -> bool:  # noqa: ARG002
        return False

    def parse(self, data: bytes, *, url: str) -> ParsedDocument:  # noqa: ARG002
        raise AssertionError("parser should not be called")


@pytest.mark.asyncio
async def test_process_document_uses_matching_parser() -> None:
    parsed, error = await process_document(
        url="https://example.test/doc.txt",
        client=_FakeClient(),
        parsers=[_TextParser()],
    )

    assert error is None
    assert parsed is not None
    assert parsed.text == "licitacion document body"
    assert parsed.parser_name == "text-test"
    assert parsed.metadata["parsed_at"]


@pytest.mark.asyncio
async def test_process_document_reports_unsupported_content() -> None:
    parsed, error = await process_document(
        url="https://example.test/doc.txt",
        client=_FakeClient(),
        parsers=[_NoopParser()],
    )

    assert parsed is None
    assert error == "no_parser_for_content_type"


@pytest.mark.asyncio
async def test_download_document_stops_streaming_after_size_cap() -> None:
    stream = _ChunkedStream([b"1234", b"5678", b"9012"])

    with pytest.raises(ValueError, match="document too large"):
        await download_document(
            "https://example.test/big.pdf",
            client=_ChunkedClient(stream),
            max_bytes=5,
        )

    assert stream.chunks_read == 2
