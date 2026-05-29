# Architecture

`licitaciones-mcp` is split into three layers.

## Core

The core layer owns public tender concepts:

- tender and document models
- CPV/date/money normalization
- dedupe keys
- structured filters
- public labels for source codes and local filter facets
- text and CPV scoring
- deterministic source-data quality checks

Core code has no dependency on MCP, HTTP clients, or Postgres sessions.

## Sources

The source layer converts external procurement feeds into normalized `Tender` objects.

v1 includes:

- `PLACSPClient` for Atom-style open-data feeds
- PLACSP official ZIP dataset periods for national, aggregated, minor-contract, assignment, and preliminary-consultation data
- `TEDClient` for TED Search API responses

Source adapters keep raw payload metadata for auditability and future parser improvements.
PLACSP normalization keeps source codes such as notice/status, procedure type,
contract type, CPV, NUTS, buyer, winner, publication metadata, and document URLs,
then exposes public labels as derived output fields. It also records deterministic
quality issues for unknown source codes, invalid CPV/NUTS values, suspicious
dates/amounts, and open tenders without a deadline.

## Server

The server layer owns runtime integration:

- Postgres persistence
- daily jobs and job runs
- source fetch run history
- pg_textsearch BM25 ranking for lexical tender search
- optional embedding providers
- MCP tool handlers
- CLI commands

Any MCP-compatible client can connect to the server endpoint and call the exposed tools. Search is structured-first: clients pass explicit filters and may use `text` for lexical search, but the server does not implicitly reinterpret natural language queries. Lexical search uses BM25 by default and supports an explicit `fts` compatibility backend for development installs. Hybrid search fuses lexical and pgvector semantic ranks. Application-specific matching profiles and business reranking stay outside this retrieval engine.
The `list_filter_options` tool exposes static catalogs plus observed local facets
so clients can discover valid statuses, CPV sectors, NUTS regions, buyers,
dataset kinds, and value/date ranges before creating searches or jobs.
