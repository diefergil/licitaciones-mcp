"""End-to-end MCP job flow against real Postgres."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from licitaciones_mcp.core.models import Tender, TenderDocument, TenderSource
from licitaciones_mcp.storage.database import TenderDatabase

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _mcp_session(database_url: str) -> AsyncIterator[ClientSession]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.setdefault("LICITACIONES_MCP_TRANSPORT", "stdio")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "licitaciones_mcp.cli", "serve-mcp", "--transport", "stdio"],
        env=env,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = result.content[0]
    return json.loads(content.text)


async def test_mcp_can_create_and_run_job_against_postgres(
    database: TenderDatabase, _database_url: str
) -> None:
    ids = await database.upsert_tenders(
        [
            Tender(
                source=TenderSource.PLACSP,
                external_id="mcp-job-1",
                title="Servicio de mantenimiento solar municipal",
                summary="Contrato de mantenimiento fotovoltaico y monitorizacion.",
                buyer_name="Ayuntamiento de Madrid",
                cpv_codes=["09332000"],
                published_at=datetime(2026, 1, 10, tzinfo=UTC),
                deadline_at=datetime(2026, 2, 10, tzinfo=UTC),
                documents=[
                    TenderDocument(
                        url="https://example.test/pliego.pdf",
                        title="Pliego tecnico",
                        document_type="technicalSpecifications",
                    )
                ],
            )
        ]
    )

    async with _mcp_session(_database_url) as session:
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert "create_daily_job" in tool_names
        assert "run_job_now" in tool_names
        assert "get_job_results" in tool_names

        create_result = _tool_payload(
            await session.call_tool(
                "create_daily_job",
                {
                    "name": "mcp-e2e-solar",
                    "text": "solar",
                    "cpv_codes": ["09332000"],
                    "only_open": False,
                    "hour_utc": 7,
                    "limit": 10,
                },
            )
        )
        job = create_result["job"]
        assert job["id"]
        assert job["filters"]["text"] == "solar"

        run_result = _tool_payload(
            await session.call_tool(
                "run_job_now",
                {"job_id": job["id"], "refresh_sources": False},
            )
        )
        assert run_result["run"]["status"] == "succeeded"
        assert run_result["result_count"] == 1

        results = _tool_payload(
            await session.call_tool("get_job_results", {"job_id": job["id"], "limit": 10})
        )
        assert results["count"] == 1
        assert results["results"][0]["tender"]["external_id"] == "mcp-job-1"

        tender = _tool_payload(await session.call_tool("get_tender", {"tender_id": ids[0]}))
        assert tender["tender"]["title"] == "Servicio de mantenimiento solar municipal"
        assert tender["documents"][0]["title"] == "Pliego tecnico"

        ocds = _tool_payload(
            await session.call_tool(
                "export_search_ocds",
                {"text": "solar", "cpv_codes": ["09332000"], "limit": 10},
            )
        )
        assert ocds["version"] == "1.1"
        assert ocds["releases"][0]["tender"]["id"] == "mcp-job-1"
