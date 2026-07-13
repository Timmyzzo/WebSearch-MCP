import os
import sys
import threading
import time
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


async def test_stdio_grok_failover_error_is_structured_and_server_stays_alive():
    class UnavailableHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"error":{"code":"upstream_unavailable","message":"temporary"}}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UnavailableHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["GROK_API_URL"] = f"http://127.0.0.1:{upstream.server_port}"
    env["GROK_API_KEY"] = "grok-secret-key"
    env["GROK_PRIMARY_MODEL"] = "primary"
    env["GROK_MODEL_MAX_ATTEMPTS"] = "1"
    env["TAVILY_ENABLED"] = "false"
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
                search_result = await session.call_tool("web_search", {"query": "question"})
                tools_after_error = await session.list_tools()
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    structured = search_result.structuredContent
    assert search_result.isError is False
    assert structured["error"] == "grok_primary_failed"
    assert structured["grok_error"]["primary_attempts"] == 1
    assert structured["grok_error"]["fallback_attempts"] == 0
    assert structured["grok_error"]["total_attempts"] == 1
    assert "grok-secret-key" not in str(structured)
    assert {tool.name for tool in tools_after_error.tools}.issuperset({"web_search", "web_fetch"})


async def test_stdio_unified_success_partial_error_validation_and_survival():
    class GrokSuccessHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = (
                b'data: {"choices":[{"delta":{"content":"Answer"},'
                b'"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    class TavilyUnavailableHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"error":{"code":"upstream_unavailable","message":"temporary"}}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    grok_upstream = ThreadingHTTPServer(("127.0.0.1", 0), GrokSuccessHandler)
    tavily_upstream = ThreadingHTTPServer(("127.0.0.1", 0), TavilyUnavailableHandler)
    grok_thread = threading.Thread(target=grok_upstream.serve_forever, daemon=True)
    tavily_thread = threading.Thread(target=tavily_upstream.serve_forever, daemon=True)
    grok_thread.start()
    tavily_thread.start()

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["GROK_API_URL"] = f"http://127.0.0.1:{grok_upstream.server_port}"
    env["GROK_API_KEY"] = "grok-secret-key"
    env["GROK_PRIMARY_MODEL"] = "primary"
    env["GROK_MODEL_MAX_ATTEMPTS"] = "1"
    env["TAVILY_API_URL"] = f"http://127.0.0.1:{tavily_upstream.server_port}"
    env["TAVILY_API_KEYS"] = "tvly-secret-key-0001,tvly-secret-key-0002"
    env["TAVILY_SERVICE_FAILURE_THRESHOLD"] = "2"
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
                success = await session.call_tool("web_search", {"query": "success"})
                partial = await session.call_tool(
                    "web_search", {"query": "partial", "extra_sources": 1}
                )
                error = await session.call_tool(
                    "get_sources", {"session_id": "missing-session"}
                )
                validation_error = await session.call_tool("web_map", {"url": "not-a-url"})
                tools_after_errors = await session.list_tools()
    finally:
        grok_upstream.shutdown()
        grok_upstream.server_close()
        tavily_upstream.shutdown()
        tavily_upstream.server_close()
        grok_thread.join(timeout=2)
        tavily_thread.join(timeout=2)

    assert success.isError is False
    assert success.structuredContent["status"] == "success"
    assert success.structuredContent["content"] == "Answer"
    assert partial.isError is False
    assert partial.structuredContent["status"] == "partial_success"
    assert partial.structuredContent["error_detail"]["service"] == "tavily"
    assert error.isError is False
    assert error.structuredContent["status"] == "error"
    assert error.structuredContent["error_detail"]["code"] == (
        "session_id_not_found_or_expired"
    )
    assert validation_error.isError is True
    assert {tool.name for tool in tools_after_errors.tools}.issuperset(
        {"web_search", "get_sources", "web_fetch", "web_map"}
    )


async def test_stdio_web_search_budget_timeout_is_structured_and_server_stays_alive():
    class SlowSearchFastModelsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"data":[{"id":"primary"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            time.sleep(0.2)
            body = b'data: {"choices":[{"delta":{"content":"late"}}]}\n\ndata: [DONE]\n\n'
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), SlowSearchFastModelsHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["GROK_API_URL"] = f"http://127.0.0.1:{upstream.server_port}"
    env["GROK_API_KEY"] = "grok-secret-key"
    env["GROK_PRIMARY_MODEL"] = "primary"
    env["GROK_MODEL_MAX_ATTEMPTS"] = "5"
    env["WEB_SEARCH_TOTAL_TIMEOUT"] = "0.05"
    env["TAVILY_ENABLED"] = "false"
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
                timed_out = await session.call_tool("web_search", {"query": "slow"})
                config_after_timeout = await session.call_tool("get_config_info", {})
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    structured = timed_out.structuredContent
    assert timed_out.isError is False
    assert structured["status"] == "error"
    assert structured["error"] == "grok_total_budget_exhausted"
    assert structured["grok_error"]["termination_reason"] == "total_budget_exhausted"
    assert structured["grok_error"]["actual_attempts"] == 1
    assert structured["grok_error"]["configured_max_attempts"] == 5
    assert config_after_timeout.isError is False
    assert config_after_timeout.structuredContent["status"] == "success"
