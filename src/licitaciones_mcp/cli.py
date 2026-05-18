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


@app.callback()
def _root(ctx: typer.Context) -> None:  # noqa: ARG001
    """Configure structured logging before any command runs."""

    from licitaciones_mcp.observability import configure_observability

    configure_observability()


@app.command("init-db")
def init_db(
    bootstrap: Annotated[
        bool,
        typer.Option(
            "--bootstrap",
            help="Use SQLAlchemy create_all instead of Alembic (for ephemeral tests).",
        ),
    ] = False,
) -> None:
    """Create or upgrade the database schema."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        await database.init_schema(use_migrations=not bootstrap)
        await database.close()

    asyncio.run(_run())
    console.print("[green]Database schema ready.[/green]")


@app.command("migrate-db")
def migrate_db(
    revision: Annotated[str, typer.Argument()] = "head",
) -> None:
    """Run database migrations to the given revision."""

    from licitaciones_mcp.storage import migrations

    migrations.upgrade(revision)
    console.print(f"[green]Database migrated to {revision}.[/green]")


db_app = typer.Typer(help="Database migration commands.")
app.add_typer(db_app, name="db")


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument()] = "head",
) -> None:
    """Run Alembic upgrade to the given revision (default: head)."""

    from licitaciones_mcp.storage import migrations

    migrations.upgrade(revision)
    console.print(f"[green]Upgraded to {revision}.[/green]")


@db_app.command("downgrade")
def db_downgrade(revision: Annotated[str, typer.Argument()]) -> None:
    """Run Alembic downgrade to the given revision."""

    from licitaciones_mcp.storage import migrations

    migrations.downgrade(revision)
    console.print(f"[green]Downgraded to {revision}.[/green]")


@db_app.command("revision")
def db_revision(
    message: Annotated[str, typer.Option("-m", "--message")],
    autogenerate: Annotated[bool, typer.Option("--autogenerate")] = False,
) -> None:
    """Create a new Alembic revision script."""

    from licitaciones_mcp.storage import migrations

    migrations.revision(message, autogenerate=autogenerate)


@db_app.command("current")
def db_current() -> None:
    """Print the current Alembic revision applied to the database."""

    from licitaciones_mcp.storage import migrations

    revision = migrations.current()
    console.print(revision or "[yellow]No Alembic revision found.[/yellow]")


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
    country: Annotated[str | None, typer.Option("--country")] = None,
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
            country=country,
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


@app.command("list-source-runs")
def list_source_runs(
    source: Annotated[str | None, typer.Option("--source")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """List recent source fetch and ingestion attempts."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.list_source_runs(source=source, status=status, limit=limit)
        await database.close()
        console.print_json(data=result)

    asyncio.run(_run())


@app.command("get-source-run")
def get_source_run(run_id: Annotated[str, typer.Argument()]) -> None:
    """Show one source fetch and ingestion attempt."""

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        service = TenderToolService(settings, database)
        result = await service.get_source_run(run_id=run_id)
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


embeddings_app = typer.Typer(help="Embedding backfill commands.")
app.add_typer(embeddings_app, name="embeddings")


@embeddings_app.command("backfill")
def embeddings_backfill(
    batch_size: Annotated[int, typer.Option("--batch-size", min=1, max=512)] = 64,
    max_batches: Annotated[int, typer.Option("--max-batches", min=1)] = 100,
) -> None:
    """Embed tenders missing a vector for the active provider/model."""

    async def _run() -> None:
        from licitaciones_mcp.embeddings.base import NullEmbedder
        from licitaciones_mcp.embeddings.factory import build_embedder
        from licitaciones_mcp.jobs.runner import _embedding_input

        settings = get_settings()
        embedder = build_embedder(settings)
        if isinstance(embedder, NullEmbedder):
            console.print(
                "[yellow]No embedding provider configured. "
                "Set LICITACIONES_EMBEDDINGS_PROVIDER=openai and OPENAI_API_KEY.[/yellow]"
            )
            return
        database = TenderDatabase(settings.database_url)
        total = 0
        for _ in range(max_batches):
            ids = await database.tender_ids_missing_embeddings(
                provider=embedder.provider, model=embedder.model, limit=batch_size
            )
            if not ids:
                break
            tenders: list[Any] = []
            for tid in ids:
                tender = await database.get_tender(tid)
                if tender is not None:
                    tenders.append(tender)
            if not tenders:
                break
            vectors = await embedder.embed([_embedding_input(t) for t in tenders])
            if len(vectors) != len(tenders):
                console.print(
                    "[yellow]Embedding provider returned a mismatched vector count; "
                    "skipping this batch.[/yellow]"
                )
                break
            items = list(zip([t.id for t in tenders], vectors, strict=True))
            written = await database.upsert_embeddings(
                provider=embedder.provider, model=embedder.model, items=items
            )
            total += written
            console.print(f"[dim]Embedded batch of {written} tenders[/dim]")
        await database.close()
        console.print(f"[green]Done. Embedded {total} tenders.[/green]")

    asyncio.run(_run())


ingest_app = typer.Typer(help="Bulk ingestion commands.")
app.add_typer(ingest_app, name="ingest")


_PLACSP_KINDS = ("licitaciones", "agregacion", "menores", "encargos", "consultas")


@ingest_app.command("backfill")
def ingest_backfill(
    source: Annotated[str, typer.Option("--source")] = "placsp",
    kind: Annotated[str, typer.Option("--kind")] = "licitaciones",
    year_from: Annotated[int, typer.Option("--from")] = 2024,
    year_to: Annotated[int, typer.Option("--to")] = 2026,
    monthly: Annotated[bool, typer.Option("--monthly/--yearly")] = True,
    limit_per_period: Annotated[int | None, typer.Option("--limit-per-period")] = None,
    insecure_tls: Annotated[bool, typer.Option("--insecure-tls")] = False,
) -> None:
    """Walk a date range of source periods, resumable via the ``ingest_cursors`` table."""

    if source != "placsp":
        raise typer.BadParameter("only --source placsp is supported in v1")
    if kind not in _PLACSP_KINDS:
        raise typer.BadParameter(f"--kind must be one of {_PLACSP_KINDS}")

    async def _run() -> None:
        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        from licitaciones_mcp.jobs.runner import SourceIngestor

        ingestor = SourceIngestor(settings, database)
        months = range(1, 13) if monthly else [None]
        periods = [(y, m) for y in range(year_from, year_to + 1) for m in months]
        for year, month in periods:
            cursor = f"{year}-{month:02d}" if month else str(year)
            existing = await database.get_ingest_cursor(source=source, kind=kind, cursor=cursor)
            if existing and existing.get("status") == "done":
                console.print(f"[dim]skip {cursor} (done)[/dim]")
                continue
            try:
                result = await ingestor.ingest_placsp_period(
                    kind=kind,
                    year=year,
                    month=month,
                    limit=limit_per_period,
                    verify_ssl=not insecure_tls,
                )
                await database.record_ingest_cursor(
                    source=source,
                    kind=kind,
                    cursor=cursor,
                    status="done",
                    result_count=len(result.tenders),
                )
                console.print(f"[green]{cursor} → {len(result.tenders)} tenders[/green]")
            except Exception as exc:  # noqa: BLE001
                await database.record_ingest_cursor(
                    source=source,
                    kind=kind,
                    cursor=cursor,
                    status="failed",
                    last_error=str(exc),
                )
                console.print(f"[red]{cursor} failed: {exc}[/red]")
        await database.close()

    asyncio.run(_run())


@ingest_app.command("ted")
def ingest_ted(
    text: Annotated[str | None, typer.Option("--text")] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv")] = None,
    country: Annotated[str, typer.Option("--country")] = "ES",
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
) -> None:
    """Pull TED notices with the given filters."""

    async def _run() -> None:
        from licitaciones_mcp.core.models import TenderFilters

        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        from licitaciones_mcp.jobs.runner import SourceIngestor

        ingestor = SourceIngestor(settings, database)
        filters = TenderFilters(text=text, cpv_codes=cpv or [], limit=limit, country=country)
        # Force the TED branch by ensuring text/cpv is set; the ingestor
        # already gates TED behind that signal.
        if not (filters.text or filters.cpv_codes):
            raise typer.BadParameter("--text or --cpv is required for TED")
        results = await ingestor.ingest_for_filters(filters)
        ted_result = next((r for r in results if r.source.value == "ted"), None)
        await database.close()
        if ted_result is None:
            console.print("[yellow]TED returned no results.[/yellow]")
            return
        console.print(
            f"[green]{len(ted_result.tenders)} TED notices ingested (country={country}).[/green]"
        )

    asyncio.run(_run())


scheduler_app = typer.Typer(help="Scheduler worker commands.")
app.add_typer(scheduler_app, name="scheduler")


@scheduler_app.command("run")
def scheduler_run(
    reload_seconds: Annotated[int, typer.Option("--reload-seconds", min=5)] = 60,
) -> None:
    """Run the APScheduler-backed daily jobs worker (blocking)."""

    async def _run() -> None:
        from licitaciones_mcp.jobs.scheduler import TenderScheduler
        from licitaciones_mcp.storage.database import TenderDatabase

        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        scheduler = TenderScheduler(settings, database, reload_interval_seconds=reload_seconds)
        try:
            await scheduler.run_forever()
        finally:
            await database.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("[yellow]scheduler stopped[/yellow]")


ocds_app = typer.Typer(help="OCDS export commands.")
app.add_typer(ocds_app, name="ocds")


@ocds_app.command("export")
def ocds_export(
    output: Annotated[Path, typer.Option("--output", "-o")],
    tender_id: Annotated[str | None, typer.Option("--tender-id")] = None,
    text: Annotated[str | None, typer.Option("--text")] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
) -> None:
    """Export one tender or a search as an OCDS release package."""

    async def _run() -> dict[str, Any]:
        from licitaciones_mcp.storage.database import TenderDatabase

        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        try:
            from licitaciones_mcp.server.tools import TenderToolService

            service = TenderToolService(settings, database)
            if tender_id:
                return await service.export_tender_ocds(tender_id=tender_id)
            return await service.export_search_ocds(text=text, cpv_codes=cpv or [], limit=limit)
        finally:
            await database.close()

    payload = asyncio.run(_run())
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote OCDS package to {output}[/green]")


@app.command("smoke")
def smoke(limit: Annotated[int, typer.Option("--limit", min=1, max=20)] = 5) -> None:
    """Hit PLACSP and TED with tiny queries to verify connectivity."""

    async def _run() -> None:
        from licitaciones_mcp.core.models import TenderFilters
        from licitaciones_mcp.jobs.runner import SourceIngestor
        from licitaciones_mcp.storage.database import TenderDatabase

        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        ingestor = SourceIngestor(settings, database)
        filters = TenderFilters(text="servicios", limit=limit)
        try:
            results = await ingestor.ingest_for_filters(filters)
            for result in results:
                console.print(
                    f"[cyan]{result.source.value}[/cyan]: {len(result.tenders)} tenders fetched"
                )
        finally:
            await database.close()

    asyncio.run(_run())


documents_app = typer.Typer(help="Document download + extraction commands.")
app.add_typer(documents_app, name="documents")


@documents_app.command("process")
def documents_process(
    batch_size: Annotated[int, typer.Option("--batch-size", min=1, max=200)] = 20,
    max_batches: Annotated[int, typer.Option("--max-batches", min=1, max=100)] = 1,
) -> None:
    """Download and parse pending tender documents."""

    async def _run() -> None:
        from licitaciones_mcp.documents.processor import process_document
        from licitaciones_mcp.http.client import make_async_client
        from licitaciones_mcp.storage.database import TenderDatabase

        settings = get_settings()
        database = TenderDatabase(settings.database_url)
        processed = 0
        failed = 0
        try:
            async with make_async_client(
                name="documents",
                rate_per_sec=2.0,
                cache_dir=settings.cache_dir,
            ) as client:
                for _ in range(max_batches):
                    pending = await database.list_pending_documents(limit=batch_size)
                    if not pending:
                        break
                    for entry in pending:
                        parsed, error = await process_document(url=entry["url"], client=client)
                        if parsed is None:
                            failed += 1
                            await database.record_document_parse(
                                document_id=entry["id"],
                                text=None,
                                sections=None,
                                parser_name=None,
                                error=error,
                            )
                            continue
                        processed += 1
                        await database.record_document_parse(
                            document_id=entry["id"],
                            text=parsed.text,
                            sections=parsed.sections,
                            parser_name=parsed.parser_name,
                            error=None,
                        )
        finally:
            await database.close()
        console.print(
            f"[green]Processed {processed} documents[/green] ([yellow]{failed} failed[/yellow])"
        )

    asyncio.run(_run())


if __name__ == "__main__":
    app()
