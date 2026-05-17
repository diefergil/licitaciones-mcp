"""Base interfaces for tender source connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from licitaciones_mcp.core.models import SourceFetchResult, TenderFilters


class TenderSourceClient(ABC):
    """Base interface for public tender source clients."""

    @abstractmethod
    async def fetch(self, filters: TenderFilters) -> SourceFetchResult:
        """Fetch tenders matching the provided filters."""
