from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    try:
        yield {}
    finally:
        from .tools.web import close_tavily_client

        await close_tavily_client()


mcp = FastMCP("grok-search", lifespan=_lifespan)
