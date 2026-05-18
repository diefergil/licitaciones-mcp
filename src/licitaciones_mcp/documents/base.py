"""Parser base types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ParsedDocument:
    """Result of parsing a document."""

    text: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    parser_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentParser(Protocol):
    """Pluggable document parser interface."""

    name: str

    def supports(self, *, content_type: str | None, url: str) -> bool:
        """Return ``True`` if this parser can handle the document."""
        ...

    def parse(self, data: bytes, *, url: str) -> ParsedDocument:
        """Extract text + sections from raw bytes."""
        ...
