from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from ..models import TavilyMapResult, TavilySearchResult
from ..tavily_reliability import (
    TavilyReliabilityManager,
    TavilyServiceState,
    is_explicitly_invalid,
    is_quota_exhausted,
    network_failure_signature,
    parse_retry_after,
    redact_keys,
    response_error_text,
)


class TavilyClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "tavily_error",
        key_statuses: list[dict[str, object]] | None = None,
        service: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.key_statuses = key_statuses or []
        self.service = service or {}

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"code": self.code, "message": self.message}
        if self.key_statuses:
            result["key_statuses"] = self.key_statuses
        if self.service:
            result["service"] = self.service
        return result


class TavilyClient:
    def __init__(
        self,
        api_url: str,
        key_provider: Callable[[], str | None] | Iterable[str],
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        reliability_manager: TavilyReliabilityManager | None = None,
        key_cooldown: float = 30.0,
        quota_cooldown: float = 3600.0,
        service_failure_threshold: int = 2,
        service_cooldown: float = 30.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.transport = transport
        self._client = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()
        self._closed = False

        if callable(key_provider):
            self._legacy_key_provider: Callable[[], str | None] | None = key_provider
            self.reliability = reliability_manager
        else:
            self._legacy_key_provider = None
            keys = list(key_provider)
            self.reliability = reliability_manager or TavilyReliabilityManager(
                keys,
                key_cooldown=key_cooldown,
                quota_cooldown=quota_cooldown,
                service_failure_threshold=service_failure_threshold,
                service_cooldown=service_cooldown,
            )

    async def __aenter__(self) -> TavilyClient:
        await self._get_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise TavilyClientError("Tavily HTTP 客户端已关闭", code="tavily_client_closed")
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self.api_url,
                    transport=self.transport,
                    timeout=90.0,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
        return self._client

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def _request(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        if self.reliability is None:
            return await self._request_legacy(endpoint, body, timeout=timeout)

        attempted: set[str] = set()
        consistent_errors: list[tuple[str, str]] = []
        while len(attempted) < len(self.reliability.raw_keys):
            api_key = await self.reliability.acquire_key(attempted)
            if api_key is None:
                break
            attempted.add(api_key)
            try:
                response = await (await self._get_client()).post(
                    endpoint,
                    headers=self._headers(api_key),
                    json=body,
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                reason = self._safe_reason(type(exc).__name__)
                await self.reliability.mark_temporary_failure(
                    api_key,
                    network_failure_signature(exc),
                    reason,
                )
                continue
            except httpx.RequestError as exc:
                reason = self._safe_reason(type(exc).__name__)
                await self.reliability.mark_temporary_failure(
                    api_key,
                    network_failure_signature(exc),
                    reason,
                )
                continue

            if response.is_success:
                data = self._json_object(response)
                await self.reliability.mark_success(api_key)
                return data

            data = self._json_or_none(response)
            error_code, raw_message = response_error_text(data, response.text)
            reason = self._safe_reason(raw_message or f"HTTP {response.status_code}")
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            status = response.status_code

            if status == 404:
                raise self._error(
                    "tavily_api_configuration_error",
                    "Tavily API 地址或版本配置错误，请检查 TAVILY_API_URL",
                )
            if status in {401, 403} or is_explicitly_invalid(error_code, raw_message):
                await self.reliability.mark_invalid(api_key, reason)
                continue
            if status in {400, 422}:
                raise self._error(
                    "tavily_request_invalid",
                    f"Tavily 请求参数错误（HTTP {status}）: {reason}",
                )
            if status == 429:
                await self.reliability.mark_rate_limited(
                    api_key,
                    quota_exhausted=is_quota_exhausted(error_code, raw_message),
                    retry_after=retry_after,
                    reason=reason,
                )
                continue
            if status == 408 or 500 <= status < 600:
                await self.reliability.mark_temporary_failure(
                    api_key,
                    f"http:{status}",
                    reason,
                )
                continue

            signature = f"{status}:{error_code or ''}:{reason}"
            consistent_errors.append((signature, reason))
            continue

        if not self.reliability.raw_keys:
            raise self._error(
                "tavily_configuration_error",
                "配置错误: Tavily API Key 未配置，请设置 TAVILY_API_KEY 或 TAVILY_API_KEYS",
            )
        service = await self.reliability.service_summary()
        if self.reliability.service_state in {
            TavilyServiceState.OPEN,
            TavilyServiceState.HALF_OPEN,
        }:
            raise await self._reliability_error(
                "tavily_service_unavailable",
                "Tavily 服务暂时不可用，服务级熔断器已打开，请稍后重试",
                service=service,
            )
        if (
            len(attempted) == len(self.reliability.raw_keys)
            and consistent_errors
            and len({signature for signature, _ in consistent_errors}) == 1
        ):
            raise self._error(
                "tavily_api_configuration_error",
                "所有 Tavily Key 对当前端点返回一致错误；请检查 TAVILY_API_URL 和 API 版本",
            )
        if consistent_errors:
            raise self._error(
                "tavily_upstream_error",
                f"Tavily API 返回错误: {consistent_errors[-1][1]}",
            )
        raise await self._reliability_error(
            "tavily_all_keys_unavailable",
            "所有 Tavily Key 均不可用；请补充有效 Key 或重新生成 Tavily Key",
            service=service,
        )

    async def _request_legacy(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        api_key = self._legacy_key_provider() if self._legacy_key_provider else None
        if not api_key:
            raise TavilyClientError(
                "配置错误: Tavily API Key 未配置，请设置 TAVILY_API_KEY 或 TAVILY_API_KEYS",
                code="tavily_configuration_error",
            )
        try:
            response = await (await self._get_client()).post(
                endpoint,
                headers=self._headers(api_key),
                json=body,
                timeout=timeout,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise TavilyClientError(
                f"Tavily 临时网络错误: {type(exc).__name__}",
                code="tavily_service_unavailable",
            ) from exc
        if response.status_code in {400, 422}:
            raise TavilyClientError(
                f"Tavily 请求参数错误（HTTP {response.status_code}）",
                code="tavily_request_invalid",
            )
        if response.status_code == 404:
            raise TavilyClientError(
                "Tavily API 地址或版本配置错误，请检查 TAVILY_API_URL",
                code="tavily_api_configuration_error",
            )
        if not response.is_success:
            raise TavilyClientError(
                f"Tavily API 返回 HTTP {response.status_code}",
                code="tavily_upstream_error",
            )
        return self._json_object(response)

    def _safe_reason(self, reason: str) -> str:
        keys = self.reliability.raw_keys if self.reliability else ()
        return redact_keys(reason, keys)[:300]

    def _error(self, code: str, message: str) -> TavilyClientError:
        return TavilyClientError(message, code=code)

    async def _reliability_error(
        self,
        code: str,
        message: str,
        *,
        service: dict[str, object],
    ) -> TavilyClientError:
        statuses = await self.reliability.status_summary() if self.reliability else []
        return TavilyClientError(
            message,
            code=code,
            key_statuses=statuses,
            service=service,
        )

    @staticmethod
    def _json_or_none(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            return None

    @classmethod
    def _json_object(cls, response: httpx.Response) -> dict[str, Any]:
        data = cls._json_or_none(response)
        if not isinstance(data, dict):
            raise TavilyClientError(
                "Tavily API 返回了无效 JSON 响应",
                code="tavily_invalid_response",
            )
        return data

    async def extract(self, url: str) -> str | None:
        data = await self._request(
            "/extract",
            {"urls": [url], "format": "markdown"},
            timeout=60.0,
        )
        results = data.get("results", [])
        if not results or not isinstance(results, list) or not isinstance(results[0], dict):
            return None
        content = results[0].get("raw_content", "")
        return content if isinstance(content, str) and content.strip() else None

    async def search(self, query: str, max_results: int = 6) -> list[TavilySearchResult]:
        data = await self._request(
            "/search",
            {
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_raw_content": False,
                "include_answer": False,
            },
            timeout=90.0,
        )
        return [
            TavilySearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=item.get("score", 0),
            )
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]

    async def map(
        self,
        url: str,
        instructions: str = "",
        max_depth: int = 1,
        max_breadth: int = 20,
        limit: int = 50,
        timeout: int = 150,
    ) -> TavilyMapResult:
        body: dict[str, Any] = {
            "url": url,
            "max_depth": max_depth,
            "max_breadth": max_breadth,
            "limit": limit,
            "timeout": timeout,
        }
        if instructions:
            body["instructions"] = instructions
        data = await self._request("/map", body, timeout=float(timeout + 10))
        return TavilyMapResult(
            base_url=data.get("base_url", ""),
            results=data.get("results", []),
            response_time=data.get("response_time", 0),
        )
