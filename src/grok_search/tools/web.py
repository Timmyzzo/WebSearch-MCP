import asyncio
from typing import Annotated

from fastmcp import Context
from pydantic import Field

from ..app import mcp
from ..clients import GrokClient, GrokClientError, TavilyClient, TavilyClientError
from ..config import config
from ..logger import log_info
from ..models import (
    GrokErrorDetail,
    Source,
    SourcesResponse,
    TavilyErrorDetail,
    TavilySearchResult,
    WebFetchResponse,
    WebMapResponse,
    WebSearchResponse,
)
from ..sources import SourcesCache, merge_sources, new_session_id, split_answer_and_sources

_SOURCES_CACHE = SourcesCache(max_size=256)
_AVAILABLE_MODELS_CACHE: dict[tuple[str, str], list[str]] = {}
_AVAILABLE_MODELS_LOCK = asyncio.Lock()
_TAVILY_CLIENT: TavilyClient | None = None
_GROK_CLIENT: GrokClient | None = None
_GROK_CLIENT_SIGNATURE: tuple[str, str] | None = None
_GROK_CLIENT_LOCK = asyncio.Lock()


def _new_grok_client(api_url: str, api_key: str) -> GrokClient:
    return GrokClient(api_url, api_key)


async def _get_grok_client(api_url: str, api_key: str) -> GrokClient:
    global _GROK_CLIENT, _GROK_CLIENT_SIGNATURE
    signature = (api_url, api_key)
    async with _GROK_CLIENT_LOCK:
        if _GROK_CLIENT is not None and _GROK_CLIENT_SIGNATURE != signature:
            await _GROK_CLIENT.aclose()
            _GROK_CLIENT = None
        if _GROK_CLIENT is None:
            _GROK_CLIENT = _new_grok_client(api_url, api_key)
            _GROK_CLIENT_SIGNATURE = signature
        return _GROK_CLIENT


def _new_tavily_client() -> TavilyClient:
    global _TAVILY_CLIENT
    if _TAVILY_CLIENT is None:
        _TAVILY_CLIENT = TavilyClient(
            config.tavily_api_url,
            config.tavily_api_keys,
            key_cooldown=config.tavily_key_cooldown,
            quota_cooldown=config.tavily_quota_cooldown,
            service_failure_threshold=config.tavily_service_failure_threshold,
            service_cooldown=config.tavily_service_cooldown,
        )
    return _TAVILY_CLIENT


async def close_tavily_client() -> None:
    global _TAVILY_CLIENT
    client = _TAVILY_CLIENT
    _TAVILY_CLIENT = None
    if client is not None:
        await client.aclose()


async def close_grok_client() -> None:
    global _GROK_CLIENT, _GROK_CLIENT_SIGNATURE
    async with _GROK_CLIENT_LOCK:
        client = _GROK_CLIENT
        _GROK_CLIENT = None
        _GROK_CLIENT_SIGNATURE = None
    if client is not None:
        await client.aclose()


def _tavily_error_detail(exc: TavilyClientError) -> TavilyErrorDetail:
    return TavilyErrorDetail.model_validate(exc.to_dict())


async def _get_available_models_cached(api_url: str, api_key: str) -> list[str]:
    key = (api_url, api_key)
    async with _AVAILABLE_MODELS_LOCK:
        if key in _AVAILABLE_MODELS_CACHE:
            return _AVAILABLE_MODELS_CACHE[key]

    try:
        models = await (await _get_grok_client(api_url, api_key)).list_models()
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
    meta={"version": "2.2.0"},
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
        configured_primary = config.grok_primary_model
        configured_fallback = config.grok_fallback_model
        max_attempts = config.grok_model_max_attempts
    except ValueError as exc:
        await _SOURCES_CACHE.set(session_id, [])
        message = f"配置错误: {exc}"
        return WebSearchResponse(
            session_id=session_id,
            content=message,
            sources_count=0,
            error="grok_configuration_error",
        )

    effective_model = configured_primary
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
        effective_model = config.normalize_model(model)

    grok_client = await _get_grok_client(api_url, api_key)
    tavily_count = extra_sources if config.tavily_api_keys else 0

    async def safe_grok() -> tuple[str | None, GrokClientError | None]:
        try:
            result = await grok_client.search(
                query,
                platform,
                primary_model=effective_model,
                fallback_model=configured_fallback,
                max_attempts=max_attempts,
            )
            return result, None
        except GrokClientError as exc:
            return None, exc

    async def safe_tavily() -> tuple[list[TavilySearchResult], TavilyClientError | None]:
        if not tavily_count:
            return [], None
        try:
            return await _new_tavily_client().search(query, tavily_count), None
        except TavilyClientError as exc:
            return [], exc

    grok_outcome, tavily_outcome = await asyncio.gather(safe_grok(), safe_tavily())
    grok_result, grok_error = grok_outcome
    tavily_results, tavily_error = tavily_outcome
    if grok_error is not None:
        await _SOURCES_CACHE.set(session_id, [])
        return WebSearchResponse(
            session_id=session_id,
            content="",
            sources_count=0,
            error=grok_error.code,
            grok_error=GrokErrorDetail.model_validate(grok_error.to_dict()),
            tavily_error=_tavily_error_detail(tavily_error) if tavily_error else None,
        )
    answer, grok_sources = split_answer_and_sources(grok_result or "")
    all_sources = merge_sources(grok_sources, _extra_results_to_sources(tavily_results))
    await _SOURCES_CACHE.set(session_id, all_sources)

    return WebSearchResponse(
        session_id=session_id,
        content=answer,
        sources_count=len(all_sources),
        partial=tavily_error is not None and bool(answer or grok_sources),
        error=(
            tavily_error.code
            if tavily_error is not None and not (answer or grok_sources)
            else None
        ),
        tavily_error=_tavily_error_detail(tavily_error) if tavily_error else None,
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
        return WebFetchResponse(
            url=url,
            error=exc.message,
            tavily_error=_tavily_error_detail(exc),
        )

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
        return WebMapResponse(error=exc.message, tavily_error=_tavily_error_detail(exc))
    return WebMapResponse(**result.model_dump())
