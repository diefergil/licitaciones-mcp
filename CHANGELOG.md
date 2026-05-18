# Changelog

All notable changes to **licitaciones-mcp** will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
