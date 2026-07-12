import asyncio
from typing import Annotated

from fastmcp import Context
from pydantic import Field

from ..app import mcp
from ..clients import GrokClient, TavilyClient, TavilyClientError
from ..config import config
from ..logger import log_info
from ..models import (
    Source,
    SourcesResponse,
    TavilySearchResult,
    WebFetchResponse,
    WebMapResponse,
    WebSearchResponse,
)
from ..sources import SourcesCache, merge_sources, new_session_id, split_answer_and_sources

_SOURCES_CACHE = SourcesCache(max_size=256)
_AVAILABLE_MODELS_CACHE: dict[tuple[str, str], list[str]] = {}
_AVAILABLE_MODELS_LOCK = asyncio.Lock()


def _new_grok_client(api_url: str, api_key: str, model: str) -> GrokClient:
    return GrokClient(api_url, api_key, model)


def _new_tavily_client() -> TavilyClient:
    return TavilyClient(config.tavily_api_url, config.next_tavily_api_key)


async def _get_available_models_cached(api_url: str, api_key: str) -> list[str]:
    key = (api_url, api_key)
    async with _AVAILABLE_MODELS_LOCK:
        if key in _AVAILABLE_MODELS_CACHE:
            return _AVAILABLE_MODELS_CACHE[key]

    try:
        models = await _new_grok_client(api_url, api_key, config.grok_model).list_models()
    except Exception:
        models = []

    async with _AVAILABLE_MODELS_LOCK:
        _AVAILABLE_MODELS_CACHE[key] = models
    return models


def _extra_results_to_sources(results: list[TavilySearchResult]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in results:
        url = result.url.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        item = {"url": url, "provider": "tavily"}
        if result.title.strip():
            item["title"] = result.title.strip()
        if result.content.strip():
            item["description"] = result.content.strip()
        sources.append(item)
    return sources


@mcp.tool(
    name="web_search",
    description=(
        "Search the web with Grok and optionally add structured Tavily sources. "
        "Returns a session_id, answer content, and cached source count."
    ),
    meta={"version": "2.1.0"},
)
async def web_search(
    query: Annotated[str, Field(description="Clear, self-contained search query.", min_length=1)],
    platform: Annotated[
        str,
        Field(description="Optional platform focus such as GitHub, Reddit, or Twitter."),
    ] = "",
    model: Annotated[
        str,
        Field(description="Optional Grok model ID for this request only."),
    ] = "",
    extra_sources: Annotated[
        int,
        Field(description="Additional Tavily source results to cache.", ge=0, le=20),
    ] = 0,
) -> WebSearchResponse:
    session_id = new_session_id()
    try:
        api_url = config.grok_api_url
        api_key = config.grok_api_key
    except ValueError as exc:
        await _SOURCES_CACHE.set(session_id, [])
        message = f"配置错误: {exc}"
        return WebSearchResponse(
            session_id=session_id,
            content=message,
            sources_count=0,
            error="grok_configuration_error",
        )

    effective_model = config.grok_model
    if model:
        available = await _get_available_models_cached(api_url, api_key)
        if available and model not in available:
            await _SOURCES_CACHE.set(session_id, [])
            return WebSearchResponse(
                session_id=session_id,
                content=f"无效模型: {model}",
                sources_count=0,
                error="invalid_model",
            )
        effective_model = model

    grok_client = _new_grok_client(api_url, api_key, effective_model)
    tavily_count = extra_sources if config.tavily_api_keys else 0

    async def safe_grok() -> str:
        try:
            return await grok_client.search(query, platform)
        except Exception:
            return ""

    async def safe_tavily() -> list[TavilySearchResult]:
        if not tavily_count:
            return []
        try:
            return await _new_tavily_client().search(query, tavily_count)
        except Exception:
            return []

    grok_result, tavily_results = await asyncio.gather(safe_grok(), safe_tavily())
    answer, grok_sources = split_answer_and_sources(grok_result or "")
    all_sources = merge_sources(grok_sources, _extra_results_to_sources(tavily_results))
    await _SOURCES_CACHE.set(session_id, all_sources)

    return WebSearchResponse(
        session_id=session_id,
        content=answer,
        sources_count=len(all_sources),
    )


@mcp.tool(
    name="get_sources",
    description="Retrieve cached sources for a previous web_search session_id.",
    meta={"version": "1.1.0"},
)
async def get_sources(
    session_id: Annotated[
        str, Field(description="Session ID returned by web_search.", min_length=1)
    ],
) -> SourcesResponse:
    sources = await _SOURCES_CACHE.get(session_id)
    if sources is None:
        return SourcesResponse(
            session_id=session_id,
            sources=[],
            sources_count=0,
            error="session_id_not_found_or_expired",
        )
    normalized = [Source.model_validate(source) for source in sources]
    return SourcesResponse(
        session_id=session_id,
        sources=normalized,
        sources_count=len(normalized),
    )


@mcp.tool(
    name="web_fetch",
    description="Extract a web page as Markdown using Tavily Extract.",
    meta={"version": "1.4.0"},
)
async def web_fetch(
    url: Annotated[
        str,
        Field(description="Complete HTTP or HTTPS URL to extract.", pattern=r"^https?://"),
    ],
    ctx: Context | None = None,
) -> WebFetchResponse:
    await log_info(ctx, f"Begin Fetch: {url}", config.debug_enabled)
    try:
        content = await _new_tavily_client().extract(url)
    except TavilyClientError as exc:
        await log_info(ctx, "Fetch Failed!", config.debug_enabled)
        return WebFetchResponse(url=url, error=str(exc))

    if content:
        await log_info(ctx, "Fetch Finished (Tavily)!", config.debug_enabled)
        return WebFetchResponse(url=url, content=content, provider="tavily")

    await log_info(ctx, "Fetch Failed!", config.debug_enabled)
    return WebFetchResponse(url=url, error="提取失败: Tavily 未能获取内容")


@mcp.tool(
    name="web_map",
    description="Discover a website's URL structure using Tavily Map.",
    meta={"version": "1.4.0"},
)
async def web_map(
    url: Annotated[
        str,
        Field(description="Root HTTP or HTTPS URL to map.", pattern=r"^https?://"),
    ],
    instructions: Annotated[
        str,
        Field(description="Optional natural-language filter instructions."),
    ] = "",
    max_depth: Annotated[int, Field(description="Maximum traversal depth.", ge=1, le=5)] = 1,
    max_breadth: Annotated[
        int,
        Field(description="Maximum links followed per page.", ge=1, le=500),
    ] = 20,
    limit: Annotated[int, Field(description="Maximum total URLs returned.", ge=1, le=500)] = 50,
    timeout: Annotated[
        int,
        Field(description="Operation timeout in seconds.", ge=10, le=150),
    ] = 150,
) -> WebMapResponse:
    try:
        result = await _new_tavily_client().map(
            url=url,
            instructions=instructions,
            max_depth=max_depth,
            max_breadth=max_breadth,
            limit=limit,
            timeout=timeout,
        )
    except TavilyClientError as exc:
        return WebMapResponse(error=str(exc))
    return WebMapResponse(**result.model_dump())
