import pytest

from licitaciones_mcp.config import Settings
from licitaciones_mcp.server.app import build_mcp


@pytest.mark.asyncio
async def test_mcp_builds_with_expected_tools() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://example:example@localhost/example",
        LICITACIONES_MCP_HOST="127.0.0.1",
        LICITACIONES_MCP_PORT=9999,
    )

    mcp = build_mcp(settings)
    tools = await mcp.list_tools()
    tool_names = {tool.name for tool in tools}

    assert {
        "search_tenders",
        "get_tender",
        "get_recent_tenders",
        "search_buyers",
        "search_cpv_codes",
        "ingest_source_period",
        "create_daily_job",
        "list_jobs",
        "run_job_now",
        "get_job_results",
        "match_tenders",
    }.issubset(tool_names)

    search_schema = next(tool.inputSchema for tool in tools if tool.name == "search_tenders")
    properties = search_schema["properties"]
    assert "text" in properties
    assert "cpv_codes" in properties
    assert "query" not in properties
