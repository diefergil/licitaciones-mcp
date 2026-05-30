# Changelog

All notable changes to **licitaciones-mcp** will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-05-29

PLACSP ingest and filter-facet release.

### Added

- Public CODICE-derived labels for PLACSP statuses, notice/status codes, contract
  types, procedure types, dataset kinds, and CPV sectors.
- `cpv_prefixes` and `dataset_kinds` filters across MCP tools, CLI search,
  daily jobs, matching input, and Postgres structured filtering.
- Prefix-aware NUTS filtering in Postgres.
- `list_filter_options` MCP tool and `filter-options` CLI command for static
  catalogs plus local facet counts and value/date ranges.
- Quality issues for unknown source codes, invalid CPV/NUTS values, suspicious
  amounts/dates, and open tenders without deadlines.

### Changed

- PLACSP parsing now extracts richer budget, deadline, location/NUTS, buyer,
  winner, award, currency, publication, and source metadata fields.
- Daily PLACSP Atom ingestion marks rows as the `licitaciones` dataset kind.

### Notes

- This release remains contract/tender focused. Subsidies/BDNS and
  application-specific business reranking remain outside this repository.
- Ingestion stores document URLs but does not automatically download or parse
  tender PDFs.

## [0.3.2] — 2026-05-29

Production healthcheck hotfix.

### Fixed

- Make the BM25 production acceptance probe use an indexed term from restored tender data instead
  of a fixed Spanish word that may not appear in every dataset.

## [0.3.1] — 2026-05-29

Postgres 18 deployment hotfix.

### Fixed

- Mount the Postgres Docker volume at `/var/lib/postgresql`, matching the PostgreSQL 18
  Docker image layout.

## [0.3.0] — 2026-05-29

Postgres 18 and production search hardening release.

### Added

- Reproducible Postgres 18 image with pgvector and pinned `pg_textsearch`.
- Required BM25 search backend by default with explicit `LICITACIONES_SEARCH_BACKEND=bm25`.
- Explicit `LICITACIONES_SEARCH_BACKEND=fts` compatibility mode for installs that cannot load
  `pg_textsearch`.
- Production health checks for `pg_textsearch`, `idx_tenders_bm25_text`, scheduler heartbeat,
  source runs, and embeddings.
- Production deployment overlay with Caddy, private MCP/Postgres services, and VPS hardening
  helpers.

### Changed

- Keyword search now preserves database lexical retrieval order and returns technical retrieval
  signals instead of application-specific matching scores.
- Hybrid search now fuses lexical and vector candidates with Reciprocal Rank Fusion.
- Integration tests now run against the Postgres 18 BM25 image.

### Security

- HTTP production deployment keeps only Caddy public and requires bearer authentication for MCP.
- Pre-commit and CI security checks cover deployment config, Bandit, and tracked-file secret
  scanning.
- Docker build context excludes local private agent files.

### Upgrade Notes

- Postgres 16 to 18 is a major database upgrade. Existing installations must recreate disposable
  volumes or use dump/restore or `pg_upgrade` before running this release.

## [0.2.0] — 2026-05-18

First installable feature release.

### Added

- **Alembic migrations** with baseline + FTS/pgvector + scheduler + documents revisions.
- **Source run history** for source refresh attempts, including status, counts, duration,
  period/cursor metadata, and sanitized errors.
- **HTTP wrapper** with retries (tenacity), per-host rate limits, and on-disk caching (hishel).
- **Source layer refactor**: clean `TenderSourceClient` interface for PLACSP + TED.
- **Hybrid search**: Spanish FTS + `pg_trgm` + `pgvector` cosine + Reciprocal Rank Fusion.
- **Embeddings pipeline**: pluggable provider, OpenAI default, opt-in via `OPENAI_API_KEY`.
- `embeddings backfill` and `ingest backfill` CLI commands with resumable `ingest_cursors`.
- **APScheduler-backed worker** with cron support and heartbeat table, exposed as
  `licitaciones-mcp scheduler run` and a dedicated `scheduler` service in compose.
- **OCDS 1.1 export**: `export_tender_ocds`, `export_search_ocds` MCP tools and
  `licitaciones-mcp ocds export` CLI; pragmatic mapper covering buyer/items/value/awards.
- **Document intelligence**: pypdf parser (default), `documents process` CLI,
  `get_tender_document` MCP tool, GIN index on extracted text.
- `semantic_search_tenders` MCP tool and `query_mode` parameter on `search_tenders`.
- `/healthz` route on HTTP transports + version logging on startup.
- `smoke` CLI for quick PLACSP+TED connectivity checks.
- Bearer-token auth middleware for HTTP transports.
- Testcontainers-based integration harness (`pgvector/pgvector:pg16`).
- Optional `docling` and `otel` extras for advanced document parsing and OpenTelemetry.

### Changed

- Default Postgres image upgraded to `pgvector/pgvector:pg16`.
- `init_schema` now runs Alembic upgrades by default.

### Security

- HTTP transport now warns loudly when started without `LICITACIONES_MCP_AUTH_TOKEN`.
- No credentials are hardcoded; all sensitive values come from environment variables.
