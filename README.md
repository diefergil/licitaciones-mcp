# licitaciones-mcp

Spain-first public procurement library and MCP server for tender search, matching, and daily alert jobs.

The project is designed as a self-hosted application. Each workspace can run its own instance with a dedicated Postgres database, job configuration, source cache, and optional embedding/LLM settings.

## What It Provides

- Python domain library for tenders, filters, scoring, dedupe, and source normalization.
- Source adapters for PLACSP Atom feeds and TED Search API responses.
- Postgres persistence for tenders, documents, saved searches, daily jobs, job runs, and optional embeddings metadata.
- MCP server exposing:
  - `search_tenders`
  - `get_tender`
  - `get_recent_tenders`
  - `search_buyers`
  - `search_cpv_codes`
  - `list_source_runs`
  - `get_source_run`
  - `ingest_source_period`
  - `create_daily_job`
  - `list_jobs`
  - `run_job_now`
  - `get_job_results`
  - `match_tenders`
- CLI for database initialization, ingestion, search, job execution, and MCP serving.
- Docker Compose deployment with Postgres.

## Quickstart

```bash
cp .env.example .env
uv sync --extra dev
uv run licitaciones-mcp migrate-db
uv run licitaciones-mcp serve-mcp
```

For Docker:

```bash
cp .env.example .env
docker compose up --build
```

## Ingest Real PLACSP Data

```bash
uv run licitaciones-mcp ingest-source-period \
  --source placsp \
  --dataset-kind licitaciones \
  --year 2026 \
  --month 5 \
  --limit 25

uv run licitaciones-mcp search gas --source placsp --limit 10
```

If your local certificate store rejects the PLACSP certificate chain, retry the ingest command with `--insecure-tls`.

## Development

```bash
uv sync --extra dev
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q
```

Do not commit `.env`, local caches, database dumps, downloaded ZIP/XML source data, or API keys.

## Structured Search and Optional Embeddings

MCP calls are structured-first. Agents or client applications should interpret user intent and call `search_tenders` with explicit filters such as `text`, `cpv_codes`, `regions`, `buyer`, `statuses`, `sources`, dates, values, and pagination. The server does not run hidden LLM query parsing in the search path.

Embeddings are disabled by default. They activate only when an embeddings provider and API key are configured.

```env
LICITACIONES_EMBEDDINGS_PROVIDER=openai
LICITACIONES_EMBEDDINGS_MODEL=text-embedding-3-small
OPENAI_API_KEY=...
```

If no provider is configured, searches still work through structured filters, CPV, region, dates, status, and keyword scoring.

When a provider is configured, `search_tenders` accepts `query_mode` (`keyword` | `semantic` | `hybrid`), and the dedicated `semantic_search_tenders` tool returns nearest-neighbour matches via pgvector.

## OCDS Export

Tenders can be exported as [OCDS 1.1](https://standard.open-contracting.org/1.1/en/) releases:

- MCP tools: `export_tender_ocds`, `export_search_ocds`.
- CLI: `licitaciones-mcp ocds export --output release-package.json --text "servicios"`.

## Document Intelligence

PLACSP/TED documents (PDF first) can be downloaded and parsed:

- Background CLI: `licitaciones-mcp documents process --batch-size 25`.
- MCP tool: `get_tender_document(document_id)` returns extracted text, sections, and parser metadata.

## Scheduler

An APScheduler-based worker runs daily/cron jobs in-process:

- `licitaciones-mcp scheduler run` (also available as a `scheduler` service in `docker-compose.yml`).
- Job definitions live in the `daily_jobs` table and can be managed via the `create_daily_job` / `run_job_now` MCP tools. Heartbeats are written to `scheduler_heartbeats`.

## Source Run History

Every source refresh records a lightweight audit row with source, operation, status, period/cursor, counts, duration, metadata, and sanitized errors. Inspect it with `licitaciones-mcp list-source-runs`, `licitaciones-mcp get-source-run <id>`, or the `list_source_runs` / `get_source_run` MCP tools.

## Health

When serving over HTTP (`streamable-http` or `sse`), the server exposes `GET /healthz` returning `{"status": "ok", "version": "..."}`.

## Source Scope

v1 is Spain-first:

- PLACSP open data / Atom-style feeds.
- Official PLACSP ZIP datasets for licitaciones, aggregated platforms, minor contracts, public-sector assignments, and preliminary consultations.
- TED API search responses for EU notices.

Autonomous community-specific scrapers are out of scope for the first release unless they can be represented through PLACSP aggregation or TED.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the tentative development plan.

## License

AGPL-3.0-only. If you modify and provide this server over a network, publish the corresponding source for those modifications.
