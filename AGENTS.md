# Repository Agent Guide

This repository is public and exposed. Treat every tracked file as public
internet-facing material. This file is safe to keep in the public repository
only because it contains open-source project guidance.

Never commit private business logic, customer-specific implementation details,
deployment topology, internal operating notes, credentials, bearer tokens, API
keys, secrets, raw customer exports, or Obsidian/private-memory content to this
repo. If a change would reveal how Nexus runs private pilots or customer
workflows, keep it out of tracked files.

## Private Local Context

If `AGENTS.local.md` exists in this checkout, read it for private deployment,
client, Obsidian, and operating-memory context before making decisions that
touch non-public work.

`AGENTS.local.md` is intentionally ignored by git. Never commit private client
scope, VPS details, bearer tokens, API keys, raw exports, credentials,
commercial notes, or internal delivery strategy to the public repo.

## Project Defaults

- Keep `licitaciones-mcp` useful as a standalone AGPL Spain-first public
  procurement library and MCP server.
- Assume all project docs, tests, fixtures, examples, issues, and PR comments
  may be read by external users.
- Preserve structured-first MCP tools. Do not hide natural-language query
  interpretation inside `search_tenders`.
- Keep communication, CRM, and human-review workflows outside the core project;
  expose structured data, events, or tool surfaces for external systems.
- Prefer official PLACSP/TED source data, auditable raw metadata, and explicit
  quality warnings over premature normalization.

## Local Commands

- Install/dev sync: `uv sync --extra dev`
- Unit tests: `uv run pytest -q`
- Pre-commit: `uv run pre-commit run --all-files`

Integration tests are marked `integration` and require Docker/Postgres.
