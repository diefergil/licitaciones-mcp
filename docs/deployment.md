# Deployment

Recommended v1 deployment is one self-hosted instance per workspace or organization.

## Server Shape

- Docker and Docker Compose 2.24.4 or newer for the production overlay
- One Postgres 18 database
- One MCP service container
- Caddy reverse proxy / TLS termination for production
- Required bearer token on the MCP HTTP transport for production
- Backups configured at the server or Postgres volume layer

## Local Install

```bash
git clone https://github.com/<your-account>/licitaciones-mcp.git
cd licitaciones-mcp
cp .env.example .env
docker compose up -d --build
```

## Production Install

Use the versioned production overlay in `deploy/production/` for internet-facing pilots.
The overlay keeps Postgres and the MCP service private on the Docker network and exposes
only Caddy on ports 80/443. It uses Compose's `!override` merge tag, which requires
Docker Compose 2.24.4 or newer.

```bash
cp deploy/production/.env.production.example .env
# Replace all placeholder secrets in .env before starting.
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build
curl -fsS "https://<host>/healthz"
```

After key-based SSH is confirmed, apply the VPS hardening helper:

```bash
sudo deploy/production/harden-vps.sh
```

Run `deploy/production/check-health.sh /opt/licitaciones-mcp` only after creating the
daily job and completing an initial ingestion, because it verifies scheduler,
source-run, and embedding acceptance signals in addition to HTTP readiness.

## MCP Connection

Point any MCP-compatible client at the server endpoint:

```text
https://<host>/mcp
```

Set `LICITACIONES_MCP_AUTH_TOKEN` to require `Authorization: Bearer <token>` on the MCP HTTP transport. Keep TLS at a reverse proxy or another trusted network edge.

## Embeddings

Embeddings are disabled unless the instance has provider settings. Search still works through structured filters and lexical scoring without model calls.

## BM25 Search

The default Compose database builds a Postgres 18 image with pgvector and
`pg_textsearch` pinned in `docker/postgres-bm25/Dockerfile`. The image starts
Postgres with `shared_preload_libraries=pg_textsearch`, migrations create
`idx_tenders_bm25_text`, and `LICITACIONES_SEARCH_BACKEND=bm25` makes BM25 a
required dependency.

Set `LICITACIONES_SEARCH_BACKEND=fts` only for explicit development or
compatibility installs that cannot load `pg_textsearch`.

Upgrading an existing Postgres 16 volume to Postgres 18 is a major-version
upgrade. Recreate the volume when data is disposable, or use a normal
dump/restore or `pg_upgrade` workflow before starting the PG18 container.

## Upgrade

```bash
git pull
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build postgres
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml run --rm migrate
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build
deploy/production/check-health.sh /opt/licitaciones-mcp
```
