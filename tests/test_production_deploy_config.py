"""Production deployment configuration guardrail tests."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = ROOT / "deploy" / "production"


def test_production_override_keeps_core_services_private_and_caddy_public() -> None:
    """Production Compose override should expose only Caddy to the internet."""

    compose = (PRODUCTION_DIR / "docker-compose.override.yml").read_text(encoding="utf-8")

    assert "postgres:" in compose
    assert "mcp:" in compose
    assert "scheduler:" in compose
    assert "caddy:" in compose
    assert "ports: !override []" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "restart: unless-stopped" in compose
    assert "LICITACIONES_CACHE_DIR: /var/cache/licitaciones-mcp" in compose
    assert "source-cache:/var/cache/licitaciones-mcp" in compose


def test_caddyfile_restricts_public_paths_to_health_and_mcp() -> None:
    """Caddy should proxy only the pilot public surface."""

    caddyfile = (PRODUCTION_DIR / "Caddyfile").read_text(encoding="utf-8")

    assert "{$LICITACIONES_PUBLIC_HOST}" in caddyfile
    assert "@allowed path /healthz /mcp /mcp/*" in caddyfile
    assert "handle @allowed" in caddyfile
    assert "reverse_proxy mcp:8080" in caddyfile
    assert "handle {" in caddyfile
    assert "respond 404" in caddyfile


def test_hardening_script_and_sshd_config_close_default_server_gaps() -> None:
    """The VPS runbook assets should lock down firewall and password SSH."""

    harden_script = (PRODUCTION_DIR / "harden-vps.sh").read_text(encoding="utf-8")
    sshd_config = (PRODUCTION_DIR / "sshd-licitaciones-hardening.conf").read_text(
        encoding="utf-8"
    )

    assert "ufw allow OpenSSH" in harden_script
    assert "ufw allow 80/tcp" in harden_script
    assert "ufw allow 443/tcp" in harden_script
    assert "ufw --force enable" in harden_script
    assert "sshd -t" in harden_script
    assert "PasswordAuthentication no" in sshd_config
    assert "KbdInteractiveAuthentication no" in sshd_config
    assert "PermitRootLogin prohibit-password" in sshd_config


def test_health_check_script_covers_mcp_auth_scheduler_and_source_runs() -> None:
    """The production monitor should verify the pilot acceptance signals."""

    script = (PRODUCTION_DIR / "check-health.sh").read_text(encoding="utf-8")

    assert "source .env" not in script
    assert "LICITACIONES_PUBLIC_HOST=" in script
    assert "docker compose exec -T mcp python - <<'PY'" in script
    assert "urllib.request.urlopen('http://127.0.0.1:8080/healthz'" in script
    assert "https://${LICITACIONES_PUBLIC_HOST}/mcp" in script
    assert "scheduler_heartbeats" in script
    assert "source_fetch_runs" in script
    assert "tender_embeddings" in script
    assert "raise exception 'database acceptance check failed" in script
    assert "zero successful source runs in the last 24 hours" in script


def test_production_env_template_documents_required_pilot_settings() -> None:
    """The env template should capture non-secret production decisions."""

    template = (PRODUCTION_DIR / ".env.production.example").read_text(encoding="utf-8")

    assert "LICITACIONES_PUBLIC_HOST=mcp.example.com" in template
    assert "LICITACIONES_MCP_AUTH_TOKEN=replace-with-generated-token" in template
    assert "LICITACIONES_EMBEDDINGS_PROVIDER=openai" in template
    assert "LICITACIONES_EMBEDDINGS_MODEL=text-embedding-3-small" in template
    assert (
        "PLACSP_FEED_URL=https://contrataciondelsectorpublico.gob.es/sindicacion/"
        "sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom"
    ) in template


def test_docs_stage_acceptance_health_after_initial_ingestion() -> None:
    """Production docs should not run acceptance checks before data exists."""

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment_doc = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    production_readme = (PRODUCTION_DIR / "README.md").read_text(encoding="utf-8")

    production_install_commands = (
        deployment_doc.split("## Production Install", maxsplit=1)[1]
        .split("```bash", maxsplit=1)[1]
        .split("```", maxsplit=1)[0]
    )

    assert "check-health.sh" not in production_install_commands
    assert "initial ingestion" in deployment_doc
    assert "Docker Compose 2.24.4" in deployment_doc
    assert "Docker Compose 2.24.4" in production_readme
    assert 'https://${LICITACIONES_PUBLIC_HOST}/healthz' not in production_readme
    quickstart = readme.split("For internet-facing pilots", maxsplit=1)[1].split(
        "## Ingest Real PLACSP Data", maxsplit=1
    )[0]
    assert "Replace every placeholder secret" in quickstart
    assert quickstart.index("Replace every placeholder secret") < quickstart.index(
        "docker compose -f docker-compose.yml"
    )
    upgrade_section = production_readme.split("## Upgrade", maxsplit=1)[1]
    assert "run --rm migrate" in production_readme
    assert upgrade_section.index("run --rm migrate") < upgrade_section.index(
        "deploy/production/check-health.sh /opt/licitaciones-mcp"
    )
