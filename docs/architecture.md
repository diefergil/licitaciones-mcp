# Architecture

`licitaciones-mcp` is split into three layers.

## Core

The core layer owns public tender concepts:

- tender and document models
- CPV/date/money normalization
- dedupe keys
- structured filters
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

## Server

The server layer owns runtime integration:

- Postgres persistence
- daily jobs and job runs
- source fetch run history
- optional embedding providers
- MCP tool handlers
- CLI commands

Any MCP-compatible client can connect to the server endpoint and call the exposed tools. Search is structured-first: clients pass explicit filters and may use `text` for lexical search, but the server does not implicitly reinterpret natural language queries.
