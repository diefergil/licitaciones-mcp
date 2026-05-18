"""Document download and parser orchestration tests."""

from __future__ import annotations

import httpx
import pytest

from licitaciones_mcp.documents.base import ParsedDocument
from licitaciones_mcp.documents.processor import process_document


class _FakeClient:
    async def get(self, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG002
        return httpx.Response(
            200,
            content=b"licitacion document body",
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", url),
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
