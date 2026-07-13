import asyncio
from typing import Annotated

from fastmcp import Context
from pydantic import Field

from ..app import mcp
from ..clients import GrokClient, GrokClientError, TavilyClient, TavilyClientError
from ..config import config
from ..logger import log_info
from ..models import (
    ErrorDetail,
    GrokErrorDetail,
    Source,
    SourcesResponse,
    TavilyErrorDetail,
    TavilyMapResult,
    TavilySearchResult,
    WebFetchResponse,
    WebMapResponse,
    WebSearchResponse,
)
from ..protocol import error_from_grok, error_from_tavily, internal_error_detail, make_error_detail
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


def _legacy_error(detail: ErrorDetail) -> str:
    return detail.code


def _unexpected_error(service: str, exc: BaseException) -> ErrorDetail:
    return internal_error_detail(service, exc)


def _grok_catalog_error(exc: BaseException) -> ErrorDetail:
    error_type = getattr(exc, "error_type", "")
    code = {
        "authentication_error": "grok_authentication_error",
        "request_invalid": "grok_request_invalid",
    }.get(error_type, "grok_model_catalog_error")
    message = (
        "Grok API 认证失败，请检查 GROK_API_KEY"
        if error_type == "authentication_error"
        else "无法读取 Grok 模型列表"
    )
    return make_error_detail(
        code=code,
        message=message,
        service="grok",
        retryable=getattr(exc, "action", "fatal") in {"retry", "switch"},
        http_status=getattr(exc, "http_status", None),
        upstream_code=getattr(exc, "upstream_code", None),
        diagnostics={"operation": "list_models", "exception_type": type(exc).__name__},
    )


async def _get_available_models_cached(api_url: str, api_key: str) -> list[str]:
    key = (api_url, api_key)
    async with _AVAILABLE_MODELS_LOCK:
        if key in _AVAILABLE_MODELS_CACHE:
            return _AVAILABLE_MODELS_CACHE[key]

    models = await (await _get_grok_client(api_url, api_key)).list_models()

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


def _tavily_results_to_evidence(
    results: list[TavilySearchResult],
    *,
    max_items: int = 12,
    max_total_chars: int = 12000,
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    total_chars = 0
    for result in results[:max_items]:
        url = result.url.strip()
        if not url:
            continue
        item = {"url": url[:2000], "provider": "tavily"}
        if result.title.strip():
            item["title"] = result.title.strip()[:300]
        if result.content.strip():
            item["snippet"] = result.content.strip()[:1200]
        item_size = sum(len(value) for value in item.values())
        if evidence and total_chars + item_size > max_total_chars:
            break
        evidence.append(item)
        total_chars += item_size
    return evidence


@mcp.tool(
    name="web_search",
    description=(
        "Research the web with Grok and optionally use structured Tavily evidence. "
        "Returns unified status/error_detail fields plus a session_id and answer content."
    ),
    meta={"version": "3.0.0"},
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
        Field(
            description="Additional Tavily results to feed into evidence synthesis and cache.",
            ge=0,
            le=20,
        ),
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
        message = f"配置错误: {exc}"
        detail = make_error_detail(
            code="grok_configuration_error",
            message=message,
            service="grok",
            retryable=False,
            diagnostics={"configuration": "grok"},
        )
        return WebSearchResponse(
            status="error",
            session_id=session_id,
            content=message,
            sources_count=0,
            error=_legacy_error(detail),
            error_detail=detail,
        )

    effective_model = configured_primary
    if model:
        try:
            available = await _get_available_models_cached(api_url, api_key)
        except Exception as exc:
            detail = _grok_catalog_error(exc)
            return WebSearchResponse(
                status="error",
                session_id=session_id,
                content="",
                sources_count=0,
                error=_legacy_error(detail),
                error_detail=detail,
            )
        if available and model not in available:
            detail = make_error_detail(
                code="invalid_model",
                message=f"无效模型: {model}",
                service="grok",
                retryable=False,
                diagnostics={"requested_model": model},
            )
            return WebSearchResponse(
                status="error",
                session_id=session_id,
                content=f"无效模型: {model}",
                sources_count=0,
                error=_legacy_error(detail),
                error_detail=detail,
            )
        effective_model = config.normalize_model(model)

    grok_client = await _get_grok_client(api_url, api_key)
    tavily_count = extra_sources

    async def safe_grok(
        supplemental_sources: list[dict[str, str]],
    ) -> tuple[str | None, GrokErrorDetail | None, ErrorDetail | None]:
        try:
            result = await grok_client.search(
                query,
                platform,
                primary_model=effective_model,
                fallback_model=configured_fallback,
                max_attempts=max_attempts,
                supplemental_sources=supplemental_sources,
            )
            return result, None, None
        except GrokClientError as exc:
            detail = GrokErrorDetail.model_validate(exc.to_dict())
            return None, detail, error_from_grok(detail)
        except Exception as exc:
            return None, None, _unexpected_error("grok", exc)

    async def safe_tavily(
    ) -> tuple[list[TavilySearchResult], TavilyErrorDetail | None, ErrorDetail | None]:
        if not tavily_count:
            return [], None, None
        try:
            return await _new_tavily_client().search(query, tavily_count), None, None
        except TavilyClientError as exc:
            detail = _tavily_error_detail(exc)
            return [], detail, error_from_tavily(detail)
        except Exception as exc:
            return [], None, _unexpected_error("tavily", exc)

    tavily_outcome = await safe_tavily()
    tavily_results, tavily_error, tavily_error_detail = tavily_outcome
    grok_outcome = await safe_grok(_tavily_results_to_evidence(tavily_results))
    grok_result, grok_error, grok_error_detail = grok_outcome
    if grok_error_detail is not None:
        if tavily_error_detail is not None:
            grok_error_detail.diagnostics["component_errors"] = {
                "tavily": tavily_error_detail.model_dump()
            }
        return WebSearchResponse(
            status="error",
            session_id=session_id,
            content="",
            sources_count=0,
            error=_legacy_error(grok_error_detail),
            error_detail=grok_error_detail,
            grok_error=grok_error,
            tavily_error=tavily_error,
        )
    if not isinstance(grok_result, str):
        detail = make_error_detail(
            code="grok_invalid_response",
            message="Grok 返回了无效响应类型，当前结果未缓存",
            service="grok",
            retryable=True,
            diagnostics={"response_type": type(grok_result).__name__},
        )
        return WebSearchResponse(
            status="error",
            session_id=session_id,
            content="",
            sources_count=0,
            error=_legacy_error(detail),
            error_detail=detail,
            tavily_error=tavily_error,
        )
    answer, grok_sources = split_answer_and_sources(grok_result)
    if not answer.strip():
        detail = make_error_detail(
            code="grok_empty_answer",
            message="Grok 响应未包含有效答案，当前结果未缓存",
            service="grok",
            retryable=True,
            diagnostics={"upstream_succeeded": True},
        )
        return WebSearchResponse(
            status="error",
            session_id=session_id,
            content="",
            sources_count=0,
            error=_legacy_error(detail),
            error_detail=detail,
            tavily_error=tavily_error,
        )
    all_sources = merge_sources(grok_sources, _extra_results_to_sources(tavily_results))
    await _SOURCES_CACHE.set(session_id, all_sources)

    is_partial = tavily_error_detail is not None
    return WebSearchResponse(
        status="partial_success" if is_partial else "success",
        session_id=session_id,
        content=answer,
        sources_count=len(all_sources),
        partial=is_partial,
        error_detail=tavily_error_detail,
        tavily_error=tavily_error,
    )


@mcp.tool(
    name="get_sources",
    description="Retrieve cached sources for a previous web_search session_id.",
    meta={"version": "2.0.0"},
)
async def get_sources(
    session_id: Annotated[
        str, Field(description="Session ID returned by web_search.", min_length=1)
    ],
) -> SourcesResponse:
    try:
        sources = await _SOURCES_CACHE.get(session_id)
    except Exception as exc:
        detail = _unexpected_error("sources_cache", exc)
        return SourcesResponse(
            status="error",
            session_id=session_id,
            sources=[],
            sources_count=0,
            error=_legacy_error(detail),
            error_detail=detail,
        )
    if sources is None:
        detail = make_error_detail(
            code="session_id_not_found_or_expired",
            message="未找到该搜索会话，session_id 可能无效或已过期",
            service="sources_cache",
            retryable=False,
            diagnostics={"session_id": session_id},
        )
        return SourcesResponse(
            status="error",
            session_id=session_id,
            sources=[],
            sources_count=0,
            error=_legacy_error(detail),
            error_detail=detail,
        )
    normalized: list[Source] = []
    invalid_count = 0
    for source in sources:
        try:
            normalized.append(Source.model_validate(source))
        except Exception:
            invalid_count += 1
    if invalid_count:
        detail = make_error_detail(
            code="sources_partially_invalid",
            message="部分缓存来源格式无效，已返回其余有效来源",
            service="sources_cache",
            retryable=False,
            diagnostics={"invalid_sources": invalid_count},
        )
        return SourcesResponse(
            status="partial_success",
            session_id=session_id,
            sources=normalized,
            sources_count=len(normalized),
            partial=True,
            error_detail=detail,
        )
    return SourcesResponse(
        status="success",
        session_id=session_id,
        sources=normalized,
        sources_count=len(normalized),
    )


@mcp.tool(
    name="web_fetch",
    description="Extract a web page as Markdown using Tavily Extract.",
    meta={"version": "2.0.0"},
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
        tavily_detail = _tavily_error_detail(exc)
        detail = error_from_tavily(tavily_detail)
        return WebFetchResponse(
            status="error",
            url=url,
            error=exc.message,
            error_detail=detail,
            tavily_error=tavily_detail,
        )
    except Exception as exc:
        await log_info(ctx, "Fetch Failed!", config.debug_enabled)
        detail = _unexpected_error("tavily", exc)
        return WebFetchResponse(
            status="error",
            url=url,
            error=_legacy_error(detail),
            error_detail=detail,
        )

    if isinstance(content, str) and content.strip():
        await log_info(ctx, "Fetch Finished (Tavily)!", config.debug_enabled)
        return WebFetchResponse(status="success", url=url, content=content, provider="tavily")

    await log_info(ctx, "Fetch Failed!", config.debug_enabled)
    detail = make_error_detail(
        code="tavily_no_content",
        message="Tavily 请求成功，但该 URL 没有可提取内容",
        service="tavily",
        retryable=False,
        diagnostics={"upstream_succeeded": True, "empty_result": True},
    )
    return WebFetchResponse(
        status="error",
        url=url,
        error=detail.message,
        error_detail=detail,
    )


@mcp.tool(
    name="web_map",
    description="Discover a website's URL structure using Tavily Map.",
    meta={"version": "2.0.0"},
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
        tavily_detail = _tavily_error_detail(exc)
        return WebMapResponse(
            status="error",
            error=exc.message,
            error_detail=error_from_tavily(tavily_detail),
            tavily_error=tavily_detail,
        )
    except Exception as exc:
        detail = _unexpected_error("tavily", exc)
        return WebMapResponse(
            status="error",
            error=_legacy_error(detail),
            error_detail=detail,
        )

    if not isinstance(result, TavilyMapResult):
        detail = make_error_detail(
            code="tavily_invalid_response",
            message="Tavily Map 返回了无效响应类型",
            service="tavily",
            retryable=True,
            diagnostics={"response_type": type(result).__name__},
        )
        return WebMapResponse(
            status="error",
            error=_legacy_error(detail),
            error_detail=detail,
        )

    if not result.results:
        detail = make_error_detail(
            code="tavily_no_urls",
            message="Tavily 请求成功，但没有发现可返回的 URL",
            service="tavily",
            retryable=False,
            diagnostics={"upstream_succeeded": True, "empty_result": True},
        )
        return WebMapResponse(
            status="error",
            base_url=result.base_url or url,
            results=[],
            response_time=result.response_time,
            ignored_results=result.ignored_results,
            error=detail.message,
            error_detail=detail,
        )
    if result.ignored_results or not result.base_url:
        detail = make_error_detail(
            code="tavily_map_incomplete",
            message="Tavily 返回了部分站点映射结果",
            service="tavily",
            retryable=False,
            diagnostics={
                "ignored_results": result.ignored_results,
                "missing_base_url": not bool(result.base_url),
            },
        )
        return WebMapResponse(
            status="partial_success",
            partial=True,
            base_url=result.base_url or url,
            results=result.results,
            response_time=result.response_time,
            ignored_results=result.ignored_results,
            error_detail=detail,
        )
    return WebMapResponse(status="success", **result.model_dump())
