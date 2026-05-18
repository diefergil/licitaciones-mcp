# Deployment

Recommended v1 deployment is one self-hosted instance per workspace or organization.

## Server Shape

- Docker and Docker Compose
- One Postgres database
- One MCP service container
- Optional reverse proxy / TLS termination
- Optional bearer token on the MCP HTTP transport
- Backups configured at the server or Postgres volume layer

## Install

```bash
git clone https://github.com/<your-account>/licitaciones-mcp.git
cd licitaciones-mcp
cp .env.example .env
docker compose up -d --build
```

## MCP Connection

Point any MCP-compatible client at the server endpoint:

```text
http://<host>:8080/mcp
```

Set `LICITACIONES_MCP_AUTH_TOKEN` to require `Authorization: Bearer <token>` on the MCP HTTP transport. Keep TLS at a reverse proxy or another trusted network edge.

## Embeddings

Embeddings are disabled unless the instance has provider settings. Search still works through structured filters and lexical scoring without model calls.

## Upgrade

```bash
git pull
docker compose up -d --build
docker compose exec mcp licitaciones-mcp migrate-db
```
