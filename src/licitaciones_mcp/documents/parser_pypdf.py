"""PDF parser backed by pypdf (default)."""

from __future__ import annotations

import io

from pypdf import PdfReader

from licitaciones_mcp.documents.base import ParsedDocument


class PyPdfParser:
    """Extract text from a PDF using pypdf, one entry per page."""

    name = "pypdf"

    def supports(self, *, content_type: str | None, url: str) -> bool:
        if content_type and "pdf" in content_type.lower():
            return True
        return url.lower().split("?", 1)[0].endswith(".pdf")

    def parse(self, data: bytes, *, url: str) -> ParsedDocument:
        reader = PdfReader(io.BytesIO(data))
        sections: list[dict[str, object]] = []
        text_parts: list[str] = []
        for index, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - pypdf throws on broken PDFs
                page_text = ""
            page_text = page_text.strip()
            if not page_text:
                continue
            sections.append({"page": index + 1, "text": page_text})
            text_parts.append(page_text)
        return ParsedDocument(
            text="\n\n".join(text_parts),
            sections=sections,
            parser_name=self.name,
            metadata={"pages": len(reader.pages)},
        )
