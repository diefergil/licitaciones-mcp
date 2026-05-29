#!/usr/bin/env bash
set -euo pipefail

cd "${1:-/opt/licitaciones-mcp}"

read_env_key() {
  local key="$1"
  local file="${2:-.env}"
  local line
  local value

  [[ -f "${file}" ]] || return 1
  line="$(grep -E "^[[:space:]]*${key}=" "${file}" | tail -n 1 || true)"
  [[ -n "${line}" ]] || return 1
  value="${line#*=}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s\n' "${value}"
}

if [[ -z "${LICITACIONES_PUBLIC_HOST:-}" ]]; then
  LICITACIONES_PUBLIC_HOST="$(read_env_key LICITACIONES_PUBLIC_HOST .env || true)"
  export LICITACIONES_PUBLIC_HOST
fi

echo "== compose =="
docker compose ps

echo "== container health =="
docker compose exec -T mcp python - <<'PY'
import urllib.request

print(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).read().decode())
PY

if [[ -z "${LICITACIONES_PUBLIC_HOST:-}" ]]; then
  echo "LICITACIONES_PUBLIC_HOST is required for production public checks" >&2
  exit 1
fi

echo "== public unauthenticated MCP status =="
status="$(curl -s -o /dev/null -w "%{http_code}" "https://${LICITACIONES_PUBLIC_HOST}/mcp")"
echo "${status}"
if [[ "${status}" != "401" ]]; then
  echo "expected public /mcp without bearer token to return 401" >&2
  exit 1
fi

echo "== database acceptance checks =="
docker compose exec -T postgres psql -U licitaciones -d licitaciones -v ON_ERROR_STOP=1 <<'SQL'
do $$
declare
  v_tenders bigint;
  v_embeddings bigint;
  v_documents bigint;
  v_enabled_jobs bigint;
  v_jobs_loaded bigint;
  v_failed_source_runs_24h bigint;
  v_succeeded_source_runs_24h bigint;
  v_bm25_score double precision;
begin
  select count(*) into v_tenders from tenders;
  select count(*) into v_embeddings from tender_embeddings;
  select count(*) into v_documents from tender_documents;
  select count(*) into v_enabled_jobs from daily_jobs where enabled is true;
  select jobs_loaded into v_jobs_loaded from scheduler_heartbeats order by beat_at desc limit 1;
  select count(*)
    into v_failed_source_runs_24h
    from source_fetch_runs
   where status = 'failed'
     and started_at >= now() - interval '24 hours';
  select count(*)
    into v_succeeded_source_runs_24h
    from source_fetch_runs
   where status = 'succeeded'
     and started_at >= now() - interval '24 hours';

  raise notice 'tenders=%', v_tenders;
  raise notice 'embeddings=%', v_embeddings;
  raise notice 'documents=%', v_documents;
  raise notice 'enabled_jobs=%', v_enabled_jobs;
  raise notice 'jobs_loaded=%', coalesce(v_jobs_loaded::text, 'NULL');
  raise notice 'failed_source_runs_24h=%', v_failed_source_runs_24h;
  raise notice 'succeeded_source_runs_24h=%', v_succeeded_source_runs_24h;

  if v_enabled_jobs <= 0 then
    raise exception 'database acceptance check failed: scheduler has no enabled jobs';
  end if;

  if coalesce(v_jobs_loaded, 0) <= 0 then
    raise exception 'database acceptance check failed: scheduler has loaded no jobs';
  end if;

  if v_succeeded_source_runs_24h <= 0 then
    raise exception 'database acceptance check failed: zero successful source runs in the last 24 hours';
  end if;

  if v_embeddings <= 0 then
    raise exception 'database acceptance check failed: embeddings table is empty';
  end if;

  if not exists (select 1 from pg_extension where extname = 'pg_textsearch') then
    raise exception 'database acceptance check failed: pg_textsearch extension is missing';
  end if;

  if to_regclass('idx_tenders_bm25_text') is null then
    raise exception 'database acceptance check failed: BM25 tender index is missing';
  end if;

  select coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(buyer_name, '')
         <@> to_bm25query(token, 'idx_tenders_bm25_text')
    into v_bm25_score
    from tenders
    cross join lateral regexp_split_to_table(lower(coalesce(title, '')), '\W+') as token
   where length(token) >= 4
   order by 1 nulls last
   limit 1;

  raise notice 'bm25_probe_score=%', coalesce(v_bm25_score::text, 'NULL');

  if v_tenders > 0 and v_bm25_score is null then
    raise exception 'database acceptance check failed: BM25 probe returned no score';
  end if;
end
$$;
SQL

echo "== public host =="
curl -fsS "https://${LICITACIONES_PUBLIC_HOST}/healthz"
echo
