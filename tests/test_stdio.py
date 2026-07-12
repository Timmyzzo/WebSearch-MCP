import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def test_standard_mcp_stdio_initialize_and_list_tools():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "grok_search.server"],
        cwd=root,
        env=env,
        encoding="utf-8",
        encoding_error_handler="replace",
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            fetch_result = await session.call_tool(
                "web_fetch",
                {"url": "https://example.com"},
            )

    assert initialized.serverInfo.name == "grok-search"
    assert {tool.name for tool in tools.tools}.issuperset(
        {"web_search", "get_sources", "web_fetch", "web_map"}
    )
    assert fetch_result.isError is False
    assert fetch_result.structuredContent["url"] == "https://example.com"
    assert "TAVILY_API_KEY" in fetch_result.structuredContent["error"]
