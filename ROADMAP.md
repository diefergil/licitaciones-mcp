# Roadmap

This roadmap is tentative and intentionally practical. The goal is to grow `licitaciones-mcp` into a self-hosted procurement intelligence toolkit: reliable ingestion, normalized public-tender data, structured search, alerts, monitoring, document analysis, and drafting workflows exposed through Python, CLI, and MCP.

The project should stay useful as a standalone open source library while also being easy to run as one instance per workspace or organization.

## Guiding Principles

- Keep official source payloads auditable and preserve raw metadata.
- Prefer deterministic structured filters over hidden natural-language parsing.
- Make expensive model usage optional and explicit.
- Design every long-running workflow to be resumable, idempotent, and observable.
- Treat Docker Compose + Postgres as the default self-hosted deployment path.
- Keep MCP tools stable and typed so agent clients can compose them safely.
- Keep communication workflows outside the core project; emit structured events that external systems can route, notify, or act on.

## Phase 1: Source Ingestion Foundation

Improve the reliability and coverage of Spain-first ingestion.

- Harden PLACSP period ingestion for all official dataset families: open tenders, aggregated platforms, minor contracts, public-sector assignments, and preliminary consultations.
- Add incremental cursors, source freshness metadata, retry/backoff, rate limits, and resumable downloads.
- Store source fetch history and ingestion diagnostics so operators can see what was fetched, parsed, skipped, or failed.
- Expand TED Search API support with pagination boundaries, field metadata, notice scopes, lots, awards, winners, values, and links back to official notices.
- Add fixture snapshots for common PLACSP/TED variants and namespace changes.

## Phase 2: Contracting Data Model

Move beyond single tender rows toward a richer procurement lifecycle model.

- Normalize buyers, suppliers, lots, awards, contracts, documents, identifiers, values, dates, CPV, NUTS, and notice types.
- Add source quality flags for missing CPV, invalid identifiers, date inconsistencies, suspicious values, duplicate notices, and incomplete awards.
- Improve dedupe and cross-source matching across PLACSP and TED using identifiers, buyer data, folder IDs, values, dates, titles, and winner data.
- Keep an export path that can map normalized records into open contracting concepts without forcing the internal model to become a strict clone of another schema.

## Phase 3: Search and Matching

Make search useful for recurring opportunity discovery.

- Add Postgres full-text search and trigram matching for title, summary, buyer, documents, CPV labels, and region fields.
- Add optional pgvector embeddings for semantic matching when an embedder is configured.
- Introduce reusable opportunity profiles with CPV, regions, buyer hints, keywords, exclusions, value ranges, and scoring weights.
- Improve `match_tenders` explanations so every score can be traced back to CPV, text, geography, value, deadline, buyer, and semantic signals.
- Add helpers for CPV lookup, buyer discovery, source coverage, and saved-search previews.

## Phase 4: Jobs, Alerts, and Monitoring

Turn saved searches into dependable daily operations.

- Add a scheduler/worker mode with persisted run state, retries, run locks, and idempotent result storage.
- Add webhook subscriptions for saved searches, job runs, source health, tender matches, and document-analysis events.
- Allow subscriptions to include routing metadata so external agent runtimes or workflow services can dispatch each event to the right process.
- Add compact webhook payloads with tender summaries, scoring reasons, deadlines, source links, document links, and idempotency keys.
- Add health checks for source freshness, parser failures, empty-result anomalies, database connectivity, and queue lag.
- Add operator-facing commands for job history, failed runs, retry now, disable/enable, and source backfill.
- Keep email delivery, inbox handling, CRM-style follow-up, and relationship management out of scope for this repository.

## Phase 5: Document Intelligence

Support deeper tender understanding while keeping model usage optional.

- Download and cache tender documents with content hashes and source provenance.
- Extract text from PDFs and office documents with safe size limits and retryable parsing.
- Link extracted clauses, requirements, dates, budgets, lots, award criteria, and submission constraints back to source documents.
- Add MCP tools for document search, tender requirement extraction, compliance checklists, and citation-backed summaries.
- Store document embeddings only when configured, and keep lexical search as the default fallback.

## Phase 6: Drafting Workflows

Add practical assistance for procurement teams without hiding source evidence.

- Generate first drafts for economic memoranda, opportunity briefs, bid/no-bid notes, and requirement matrices.
- Support reusable organization profiles, capabilities, references, assumptions, and pricing inputs stored locally.
- Produce drafts with explicit citations to tender documents and clear sections that need human review.
- Add export formats for Markdown and structured JSON before considering office-document generation.
- Keep generation tools opt-in and separate from ingestion/search tools.

## Phase 7: Self-Hosted Operations

Make deployments boring and repeatable.

- Add migrations instead of schema creation-only startup.
- Add backup/restore docs for Postgres volumes and source caches.
- Add production deployment examples for Docker Compose behind a reverse proxy.
- Add first-party auth or documented reverse-proxy auth patterns for exposed MCP endpoints.
- Add structured logs, metrics, and health endpoints suitable for uptime monitoring.
- Add release notes, versioned Docker images, and upgrade checks.

## Phase 8: Ecosystem and Governance

Make the project easier to adopt and contribute to.

- Publish stable Python APIs for parsers, filters, scoring, storage, and MCP service wiring.
- Document extension points for new sources, alert sinks, embedders, exporters, and drafting templates.
- Add compatibility tests for MCP tool schemas.
- Add contributor-friendly fixtures and source parser examples.
- Keep the roadmap public, conservative, and tied to working releases rather than speculative features.

## Near-Term Milestones

- `0.1.x`: stabilize structured MCP search, PLACSP period ingestion, TED parsing, quality flags, CI/security baseline, and Docker smoke tests.
- `0.2.x`: add migrations, source fetch history, incremental ingestion, full-text search, richer PLACSP/TED fixtures, and job run diagnostics.
- `0.3.x`: add document download/extraction, document search, requirement extraction, and citation-backed tender summaries.
- `0.4.x`: add profile-based matching, alert events, monitoring commands, and webhook subscriptions.
- `0.5.x`: add drafting helpers for economic memoranda, opportunity briefs, and compliance matrices.
