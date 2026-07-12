import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    assert fetch_result.structuredContent["tavily_error"]["code"] == "tavily_configuration_error"


async def test_stdio_tavily_error_is_structured_and_server_stays_alive():
    class UnauthorizedHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"error":{"code":"invalid_api_key","message":"revoked"}}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UnauthorizedHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["TAVILY_API_URL"] = f"http://127.0.0.1:{upstream.server_port}"
    env["TAVILY_API_KEYS"] = "tvly-secret-key-0001,tvly-secret-key-0002"
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "grok_search.server"],
        cwd=root,
        env=env,
        encoding="utf-8",
        encoding_error_handler="replace",
    )

    try:
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                fetch_result = await session.call_tool(
                    "web_fetch",
                    {"url": "https://example.com"},
                )
                tools_after_error = await session.list_tools()
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    structured = fetch_result.structuredContent
    assert fetch_result.isError is False
    assert structured["tavily_error"]["code"] == "tavily_all_keys_unavailable"
    serialized = str(structured)
    assert "tvly-secret-key-0001" not in serialized
    assert "tvly-secret-key-0002" not in serialized
    assert {tool.name for tool in tools_after_error.tools}.issuperset({"web_fetch", "web_map"})
