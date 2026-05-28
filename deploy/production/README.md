# Production deployment

This folder contains the versioned production overlay for the pilot MCP instance.

## Server layout

- App directory: `/opt/licitaciones-mcp`
- Public host: your deployment hostname, for example `mcp.example.com`
- Public ports: `80`, `443`
- Private MCP: Docker network only, proxied by Caddy
- Private Postgres: Docker network only

## First install

1. Point DNS for your deployment hostname to the server IPv4.
2. Confirm the server has Docker Compose 2.24.4 or newer. The overlay uses Compose's
   `!override` merge tag to remove host-published ports from private services.
3. Copy `.env.production.example` to `/opt/licitaciones-mcp/.env`.
4. Replace all secret placeholders in `.env`; keep the embeddings key restricted to embeddings.
5. Start the stack:

```bash
cd /opt/licitaciones-mcp
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build
curl -fsS "https://<host>/healthz"
```

6. Harden SSH and firewall after key-based SSH is confirmed:

```bash
sudo deploy/production/harden-vps.sh
```

## Daily data pipeline

Create or keep the daily recent PLACSP job:

```bash
docker compose exec mcp licitaciones-mcp create-job \
  --name recent-placsp-daily \
  --source placsp \
  --hour-utc 6 \
  --all-statuses \
  --limit 100
```

The job refreshes `PLACSP_FEED_URL`, upserts tenders and documents metadata, and embeds tender
summaries. It does not download or store PDF binaries.

## Health checks

Run the full acceptance health check after the daily job exists and at least
one initial ingestion has completed:

```bash
deploy/production/check-health.sh /opt/licitaciones-mcp
```

Acceptance signals:

- `GET /healthz` returns `200`.
- `GET /mcp` without bearer returns `401`.
- Latest scheduler heartbeat has `jobs_loaded = 1`.
- At least one source run succeeds daily.
- Tender embeddings count is non-zero and grows when new tenders are added.

## Upgrade

```bash
cd /opt/licitaciones-mcp
git pull
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build postgres
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml run --rm migrate
docker compose -f docker-compose.yml -f deploy/production/docker-compose.override.yml up -d --build
deploy/production/check-health.sh /opt/licitaciones-mcp
```
