# licitaciones-mcp

Spain-first public procurement library and MCP server for tender search, matching, and daily alert jobs.

The project is designed as a self-hosted application. Each workspace can run its own instance with a dedicated Postgres database, job configuration, source cache, and optional embedding/LLM settings.

## What It Provides

- Python domain library for tenders, filters, scoring, dedupe, and source normalization.
- Source adapters for PLACSP Atom feeds and TED Search API responses.
- Postgres persistence for tenders, documents, saved searches, daily jobs, job runs, and optional embeddings metadata.
- MCP server exposing:
  - `search_tenders`
  - `list_filter_options`
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
  - `semantic_search_tenders`
  - `export_tender_ocds`
  - `export_search_ocds`
  - `get_tender_document`
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

For internet-facing pilots, use the production overlay in `deploy/production/`.
It keeps Postgres and MCP private and exposes only Caddy on 80/443:

```bash
cp deploy/production/.env.production.example .env
# Replace every placeholder secret in .env before starting the public stack.
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build
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
The ingest path stores official document URLs and metadata. It does not download
or parse tender PDFs automatically.

## Development

```bash
uv sync --extra dev
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q
```

Do not commit `.env`, local caches, database dumps, downloaded ZIP/XML source data, or API keys.

## Structured Search and Optional Embeddings

MCP calls are structured-first. Agents or client applications should interpret user intent and call `search_tenders` with explicit filters such as `text`, `cpv_codes`, `cpv_prefixes`, `nuts_codes`, `regions`, `buyer`, `statuses`, `sources`, `dataset_kinds`, dates, values, and pagination. The server does not run hidden LLM query parsing in the search path.

Use `list_filter_options` before creating saved searches or jobs when a client
needs real local facets. It returns static public catalogs and observed counts
for statuses, notice types, contract types, procedure types, CPV codes/prefixes,
NUTS codes, regions, buyers, dataset kinds, sources, and value/date ranges.
Facets are computed over the newest matching rows up to the response's
`facet_row_window`; `truncated=true` means the local table has more matching rows
than the sampled window.

Lexical ranking uses Postgres BM25 by default. The bundled Docker database is
Postgres 18 with pgvector and `pg_textsearch`; migrations create
`idx_tenders_bm25_text`, and `text` searches rank candidates with BM25. Set
`LICITACIONES_SEARCH_BACKEND=fts` only for explicit development or compatibility
installs that need the built-in Spanish `tsvector` + `pg_trgm` path.
`query_mode="hybrid"` combines lexical and pgvector semantic ranks through
reciprocal rank fusion.

Search scores are retrieval signals from BM25, vector distance, or rank fusion.
Application-specific matching profiles and business reranking should live in the
client or integration layer that consumes this server.

Examples:

```bash
# Open ICT tenders in Madrid using CPV 72* and NUTS ES3*
uv run licitaciones-mcp search --cpv-prefix 72 --nuts ES3 --only-open

# Minor contracts for an exact CPV code
uv run licitaciones-mcp search --cpv 72000000 --dataset-kind menores

# Inspect facets before creating a daily job
uv run licitaciones-mcp filter-options --cpv-prefix 72 --only-open
```

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

Ingestion keeps document URLs linked to each tender. PDF download/parsing is a
separate optional workflow, not part of the daily PLACSP ingest path:

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
Subsidies/BDNS are not modeled in this project; they should be implemented as a
separate source and domain if needed.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the tentative development plan.

## License

AGPL-3.0-only. If you modify and provide this server over a network, publish the corresponding source for those modifications.
