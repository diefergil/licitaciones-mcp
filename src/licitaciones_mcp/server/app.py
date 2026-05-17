"""FastMCP application wiring."""

from __future__ import annotations

from typing import Any, Literal, cast

from mcp.server.fastmcp import FastMCP

from licitaciones_mcp.config import Settings, get_settings
from licitaciones_mcp.server.tools import TenderToolService
from licitaciones_mcp.storage.database import TenderDatabase


def build_mcp(settings: Settings | None = None) -> FastMCP:
    """Build the MCP server application and register tools."""

    runtime_settings = settings or get_settings()
    mcp = FastMCP(
        "licitaciones-mcp",
        host=runtime_settings.mcp_host,
        port=runtime_settings.mcp_port,
    )
    database = TenderDatabase(runtime_settings.database_url)
    service = TenderToolService(runtime_settings, database)

    @mcp.tool()
    async def search_tenders(
        text: str | None = None,
        cpv_codes: list[str] | None = None,
        nuts_codes: list[str] | None = None,
        regions: list[str] | None = None,
        buyer: str | None = None,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
        procedure_types: list[str] | None = None,
        contract_types: list[str] | None = None,
        notice_types: list[str] | None = None,
        only_open: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "score",
        order: str = "desc",
        refresh_sources: bool = False,
    ) -> dict[str, Any]:
        """Search tenders using explicit structured filters and optional source refresh."""

        return await service.search_tenders(
            text=text,
            cpv_codes=cpv_codes,
            nuts_codes=nuts_codes,
            regions=regions,
            buyer=buyer,
            statuses=statuses,
            sources=sources,
            procedure_types=procedure_types,
            contract_types=contract_types,
            notice_types=notice_types,
            only_open=only_open,
            published_from=published_from,
            published_to=published_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            min_value=min_value,
            max_value=max_value,
            limit=limit,
            offset=offset,
            order_by=cast(Any, order_by),
            order=cast(Any, order),
            refresh_sources=refresh_sources,
        )

    @mcp.tool()
    async def get_tender(tender_id: str) -> dict[str, Any]:
        """Return one tender with documents and raw source metadata."""

        return await service.get_tender(tender_id=tender_id)

    @mcp.tool()
    async def get_recent_tenders(limit: int = 20, source: str | None = None) -> dict[str, Any]:
        """Return recently published tenders from local storage."""

        return await service.get_recent_tenders(limit=limit, source=source)

    @mcp.tool()
    async def search_buyers(text: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search buyer names observed in local storage."""

        return await service.search_buyers(text=text, limit=limit)

    @mcp.tool()
    async def search_cpv_codes(text: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search CPV codes observed in local storage."""

        return await service.search_cpv_codes(text=text, limit=limit)

    @mcp.tool()
    async def ingest_source_period(
        source: str = "placsp",
        dataset_kind: str = "licitaciones",
        year: int = 2026,
        month: int | None = None,
        limit: int | None = None,
        insecure_tls: bool = False,
    ) -> dict[str, Any]:
        """Download and ingest one official source period into local storage."""

        return await service.ingest_source_period(
            source=source,
            dataset_kind=dataset_kind,
            year=year,
            month=month,
            limit=limit,
            insecure_tls=insecure_tls,
        )

    @mcp.tool()
    async def create_daily_job(
        name: str,
        text: str | None = None,
        cpv_codes: list[str] | None = None,
        regions: list[str] | None = None,
        buyer: str | None = None,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
        only_open: bool = True,
        hour_utc: int = 7,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Create or replace a persistent daily tender search job."""

        return await service.create_daily_job(
            name=name,
            text=text,
            cpv_codes=cpv_codes,
            regions=regions,
            buyer=buyer,
            statuses=statuses,
            sources=sources,
            only_open=only_open,
            hour_utc=hour_utc,
            limit=limit,
        )

    @mcp.tool()
    async def list_jobs(include_disabled: bool = False) -> dict[str, Any]:
        """List daily tender jobs configured for this instance."""

        return await service.list_jobs(include_disabled=include_disabled)

    @mcp.tool()
    async def run_job_now(job_id: str, refresh_sources: bool = True) -> dict[str, Any]:
        """Run one saved daily job immediately."""

        return await service.run_job_now(job_id=job_id, refresh_sources=refresh_sources)

    @mcp.tool()
    async def get_job_results(job_id: str, limit: int = 50) -> dict[str, Any]:
        """Return latest persisted results for a saved daily job."""

        return await service.get_job_results(job_id=job_id, limit=limit)

    @mcp.tool()
    async def match_tenders(
        profile: dict[str, Any],
        limit: int = 20,
        refresh_sources: bool = False,
    ) -> dict[str, Any]:
        """Match tenders against a company/profile payload."""

        return await service.match_tenders(
            profile=profile, limit=limit, refresh_sources=refresh_sources
        )

    return mcp


def run_mcp_server(
    *,
    host: str | None = None,
    port: int | None = None,
    transport: str | None = None,
) -> None:
    """Run the MCP server."""

    settings = get_settings()
    if host is not None:
        settings.mcp_host = host
    if port is not None:
        settings.mcp_port = port
    mcp = build_mcp(settings)
    selected_transport = cast(
        Literal["stdio", "sse", "streamable-http"], transport or settings.mcp_transport
    )
    mcp.run(transport=selected_transport)
