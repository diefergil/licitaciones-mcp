"""Command-line interface for licitaciones-mcp."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from licitaciones_mcp.config import get_settings
from licitaciones_mcp.server.app import run_mcp_server
from licitaciones_mcp.server.tools import TenderToolService
from licitaciones_mcp.sources.placsp import parse_placsp_atom
from licitaciones_mcp.sources.ted import parse_ted_search_response
from licitaciones_mcp.storage.database import TenderDatabase

app = typer.Typer(help="Licitaciones library and MCP server.")
console = Console()


@app.command("init-db")
def init_db() -> None:
    """Create database tables."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        await database.init_schema()
        await database.close()

    asyncio.run(_run())
    console.print("[green]Database schema ready.[/green]")


@app.command("serve-mcp")
def serve_mcp(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    transport: Annotated[str | None, typer.Option("--transport")] = None,
) -> None:
    """Run the MCP server."""

    run_mcp_server(host=host, port=port, transport=transport)


@app.command("ingest-file")
def ingest_file(
    source: Annotated[str, typer.Option("--source", help="placsp or ted")],
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Ingest a local PLACSP XML or TED JSON fixture/snapshot."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        if source == "placsp":
            tenders = parse_placsp_atom(path.read_text(encoding="utf-8"))
        elif source == "ted":
            tenders = parse_ted_search_response(json.loads(path.read_text(encoding="utf-8")))
        else:
            raise typer.BadParameter("source must be 'placsp' or 'ted'")
        ids = await database.upsert_tenders(tenders)
        await database.close()
        console.print(f"[green]Ingested {len(ids)} tenders.[/green]")

    asyncio.run(_run())


@app.command("search")
def search(
    text: Annotated[str | None, typer.Argument()] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv")] = None,
    nuts: Annotated[list[str] | None, typer.Option("--nuts")] = None,
    region: Annotated[list[str] | None, typer.Option("--region")] = None,
    buyer: Annotated[str | None, typer.Option("--buyer")] = None,
    status: Annotated[list[str] | None, typer.Option("--status")] = None,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    only_open: Annotated[bool, typer.Option("--only-open")] = False,
    refresh_sources: Annotated[bool, typer.Option("--refresh-sources")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """Search local tenders."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.search_tenders(
            text=text,
            cpv_codes=cpv,
            nuts_codes=nuts,
            regions=region,
            buyer=buyer,
            statuses=status,
            sources=source,
            only_open=only_open,
            refresh_sources=refresh_sources,
            limit=limit,
        )
        await database.close()
        _print_results(result["results"])

    asyncio.run(_run())


@app.command("recent")
def recent(
    source: Annotated[str | None, typer.Option("--source")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """Show recently published tenders."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.get_recent_tenders(source=source, limit=limit)
        await database.close()
        _print_results(result["results"])

    asyncio.run(_run())


@app.command("buyers")
def buyers(
    text: Annotated[str | None, typer.Argument()] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """Search buyer names stored locally."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.search_buyers(text=text, limit=limit)
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("cpv-codes")
def cpv_codes(
    text: Annotated[str | None, typer.Argument()] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """Search CPV codes stored locally."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.search_cpv_codes(text=text, limit=limit)
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("ingest-source-period")
def ingest_source_period(
    source: Annotated[str, typer.Option("--source")] = "placsp",
    dataset_kind: Annotated[str, typer.Option("--dataset-kind")] = "licitaciones",
    year: Annotated[int, typer.Option("--year")] = 2026,
    month: Annotated[int | None, typer.Option("--month")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    insecure_tls: Annotated[bool, typer.Option("--insecure-tls")] = False,
) -> None:
    """Download and ingest one official source period."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.ingest_source_period(
            source=source,
            dataset_kind=dataset_kind,
            year=year,
            month=month,
            limit=limit,
            insecure_tls=insecure_tls,
        )
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("create-job")
def create_job(
    name: Annotated[str, typer.Option("--name")],
    text: Annotated[str | None, typer.Option("--text")] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv")] = None,
    region: Annotated[list[str] | None, typer.Option("--region")] = None,
    buyer: Annotated[str | None, typer.Option("--buyer")] = None,
    status: Annotated[list[str] | None, typer.Option("--status")] = None,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    hour_utc: Annotated[int, typer.Option("--hour-utc", min=0, max=23)] = 7,
    only_open: Annotated[bool, typer.Option("--only-open/--all-statuses")] = True,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """Create or replace a daily job."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.create_daily_job(
            name=name,
            text=text,
            cpv_codes=cpv,
            regions=region,
            buyer=buyer,
            statuses=status,
            sources=source,
            only_open=only_open,
            hour_utc=hour_utc,
            limit=limit,
        )
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("run-job")
def run_job(
    job_id: Annotated[str, typer.Argument()],
    refresh_sources: Annotated[bool, typer.Option("--refresh-sources/--no-refresh-sources")] = True,
) -> None:
    """Run a daily job immediately."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.run_job_now(job_id=job_id, refresh_sources=refresh_sources)
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("run-due-jobs")
def run_due_jobs() -> None:
    """Run enabled jobs due in the current UTC hour."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        from licitaciones_mcp.jobs.runner import DailyJobRunner

        runner = DailyJobRunner(database, settings)
        results = await runner.run_due_jobs()
        await database.close()
        console.print_json(
            data=[
                {"run": item.run.model_dump(mode="json"), "count": item.result_count}
                for item in results
            ]
        )

    asyncio.run(_run())


def _print_results(results: list[dict[str, Any]]) -> None:
    table = Table(title="Tender Results")
    table.add_column("Score", justify="right")
    table.add_column("Source")
    table.add_column("Title")
    table.add_column("Buyer")
    table.add_column("Deadline")
    for item in results:
        tender = item["tender"]
        table.add_row(
            str(item.get("score", "")),
            tender["source"],
            tender["title"][:80],
            str(tender.get("buyer_name") or "")[:40],
            str(tender.get("deadline_at") or ""),
        )
    console.print(table)


if __name__ == "__main__":
    app()
