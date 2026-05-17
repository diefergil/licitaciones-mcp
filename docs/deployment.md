# Deployment

Recommended v1 deployment is one self-hosted instance per workspace or organization.

## Server Shape

- Docker and Docker Compose
- One Postgres database
- One MCP service container
- Optional reverse proxy / TLS termination
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

Use bearer/API-key auth at the reverse proxy layer until the MCP server grows first-party auth.

## Embeddings

Embeddings are disabled unless the instance has provider settings. Search still works through structured filters and lexical scoring without model calls.

## Upgrade

```bash
git pull
docker compose up -d --build
docker compose exec mcp licitaciones-mcp init-db
```
