"""High-level orchestration: download → parse → persist."""

from __future__ import annotations

from datetime import UTC, datetime

from licitaciones_mcp.documents.base import DocumentParser, ParsedDocument
from licitaciones_mcp.documents.downloader import AsyncDocumentClient, download_document
from licitaciones_mcp.documents.parser_pypdf import PyPdfParser


def default_parsers() -> list[DocumentParser]:
    """Return the built-in parser stack (override via DI for tests/extras)."""

    return [PyPdfParser()]


def pick_parser(
    parsers: list[DocumentParser], *, content_type: str | None, url: str
) -> DocumentParser | None:
    for parser in parsers:
        if parser.supports(content_type=content_type, url=url):
            return parser
    return None


async def process_document(
    *, url: str, client: AsyncDocumentClient, parsers: list[DocumentParser] | None = None
) -> tuple[ParsedDocument | None, str | None]:
    """Download and parse a document; return (parsed, error_message)."""

    active = parsers or default_parsers()
    try:
        downloaded = await download_document(url, client=client)
    except Exception as exc:  # noqa: BLE001
        return None, f"download_failed: {exc}"
    parser = pick_parser(active, content_type=downloaded.content_type, url=url)
    if parser is None:
        return None, "no_parser_for_content_type"
    try:
        parsed = parser.parse(downloaded.content, url=url)
    except Exception as exc:  # noqa: BLE001
        return None, f"parse_failed: {exc}"
    parsed.metadata.setdefault("parsed_at", datetime.now(UTC).isoformat())
    return parsed, None
