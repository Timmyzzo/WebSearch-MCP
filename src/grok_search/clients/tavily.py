from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from ..budget import RequestBudget
from ..models import TavilyMapResult, TavilySearchResult
from ..protocol import sanitize_diagnostic_text
from ..tavily_reliability import (
    TavilyConcurrencyTimeout,
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
        retryable: bool = False,
        http_status: int | None = None,
        upstream_code: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.key_statuses = key_statuses or []
        self.service = service or {}
        self.retryable = retryable
        self.http_status = http_status
        self.upstream_code = upstream_code
        self.diagnostics = diagnostics or {}

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "component": "tavily",
            "retryable": self.retryable,
            "http_status": self.http_status,
            "upstream_code": self.upstream_code,
            "diagnostics": self.diagnostics,
        }
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
        per_key_max_concurrency: int = 1,
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
                per_key_max_concurrency=per_key_max_concurrency,
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
        budget: RequestBudget | None = None,
    ) -> dict[str, Any]:
        request_budget = budget or RequestBudget(timeout)
        if self.reliability is None:
            return await self._request_legacy(
                endpoint,
                body,
                timeout=timeout,
                budget=request_budget,
            )

        attempted: set[str] = set()
        consistent_errors: list[tuple[str, str]] = []
        last_http_status: int | None = None
        last_upstream_code: str | None = None
        while len(attempted) < len(self.reliability.raw_keys):
            wait_started = time.monotonic()
            try:
                api_key = await self.reliability.acquire_key_slot(
                    attempted,
                    timeout=request_budget.remaining(),
                )
            except TavilyConcurrencyTimeout as exc:
                request_budget.record_queue_wait("tavily", time.monotonic() - wait_started)
                raise self._budget_error(
                    request_budget,
                    code="tavily_concurrency_timeout",
                    message="等待上游并发槽位时预算耗尽",
                    termination_reason="concurrency_queue_timeout",
                ) from exc
            request_budget.record_queue_wait("tavily", time.monotonic() - wait_started)
            if api_key is None:
                break
            attempted.add(api_key)
            try:
                try:
                    remaining = request_budget.remaining()
                    if remaining <= 0:
                        raise self._budget_error(
                            request_budget,
                            code="tavily_total_budget_exhausted",
                            message="Tavily 请求总时间预算已耗尽",
                            termination_reason="total_budget_exhausted",
                        )
                    async with asyncio.timeout(remaining):
                        response = await (await self._get_client()).post(
                            endpoint,
                            headers=self._headers(api_key),
                            json=body,
                            timeout=min(timeout, remaining),
                        )
                except TimeoutError as exc:
                    raise self._budget_error(
                        request_budget,
                        code="tavily_total_budget_exhausted",
                        message="Tavily 请求总时间预算已耗尽",
                        termination_reason="total_budget_exhausted",
                    ) from exc
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
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                status = response.status_code
                last_http_status = status
                last_upstream_code = self._safe_upstream_code(error_code)
                reason = last_upstream_code or f"HTTP {status}"

                if status == 404:
                    raise self._error(
                        "tavily_api_configuration_error",
                        "Tavily API 地址或版本配置错误，请检查 TAVILY_API_URL",
                        http_status=status,
                        upstream_code=last_upstream_code,
                    )
                if status in {401, 403} or is_explicitly_invalid(error_code, raw_message):
                    await self.reliability.mark_invalid(api_key, reason)
                    continue
                if status in {400, 422}:
                    raise self._error(
                        "tavily_request_invalid",
                        f"Tavily 请求参数错误（HTTP {status}）: {reason}",
                        http_status=status,
                        upstream_code=last_upstream_code,
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
            finally:
                await self._release_key_safely(api_key)

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
                http_status=last_http_status,
                upstream_code=last_upstream_code,
            )
        if (
            len(attempted) == len(self.reliability.raw_keys)
            and consistent_errors
            and len({signature for signature, _ in consistent_errors}) == 1
        ):
            raise self._error(
                "tavily_api_configuration_error",
                "所有 Tavily Key 对当前端点返回一致错误；请检查 TAVILY_API_URL 和 API 版本",
                http_status=last_http_status,
                upstream_code=last_upstream_code,
            )
        if consistent_errors:
            raise self._error(
                "tavily_upstream_error",
                f"Tavily API 返回错误: {consistent_errors[-1][1]}",
                retryable=False,
                http_status=last_http_status,
                upstream_code=last_upstream_code,
            )
        raise await self._reliability_error(
            "tavily_all_keys_unavailable",
            "所有 Tavily Key 均不可用；请补充有效 Key 或重新生成 Tavily Key",
            service=service,
            http_status=last_http_status,
            upstream_code=last_upstream_code,
        )

    async def _request_legacy(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        timeout: float,
        budget: RequestBudget,
    ) -> dict[str, Any]:
        api_key = self._legacy_key_provider() if self._legacy_key_provider else None
        if not api_key:
            raise TavilyClientError(
                "配置错误: Tavily API Key 未配置，请设置 TAVILY_API_KEY 或 TAVILY_API_KEYS",
                code="tavily_configuration_error",
            )
        try:
            remaining = budget.remaining()
            if remaining <= 0:
                raise self._budget_error(
                    budget,
                    code="tavily_total_budget_exhausted",
                    message="Tavily 请求总时间预算已耗尽",
                    termination_reason="total_budget_exhausted",
                )
            async with asyncio.timeout(remaining):
                response = await (await self._get_client()).post(
                    endpoint,
                    headers=self._headers(api_key),
                    json=body,
                    timeout=min(timeout, remaining),
                )
        except TimeoutError as exc:
            raise self._budget_error(
                budget,
                code="tavily_total_budget_exhausted",
                message="Tavily 请求总时间预算已耗尽",
                termination_reason="total_budget_exhausted",
            ) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise TavilyClientError(
                f"Tavily 临时网络错误: {type(exc).__name__}",
                code="tavily_service_unavailable",
                retryable=True,
            ) from exc
        if response.status_code in {400, 422}:
            raise TavilyClientError(
                f"Tavily 请求参数错误（HTTP {response.status_code}）",
                code="tavily_request_invalid",
                http_status=response.status_code,
            )
        if response.status_code == 404:
            raise TavilyClientError(
                "Tavily API 地址或版本配置错误，请检查 TAVILY_API_URL",
                code="tavily_api_configuration_error",
                http_status=response.status_code,
            )
        if not response.is_success:
            raise TavilyClientError(
                f"Tavily API 返回 HTTP {response.status_code}",
                code="tavily_upstream_error",
                retryable=response.status_code in {408, 429}
                or 500 <= response.status_code < 600,
                http_status=response.status_code,
            )
        return self._json_object(response)

    def _safe_reason(self, reason: str) -> str:
        keys = self.reliability.raw_keys if self.reliability else ()
        return sanitize_diagnostic_text(redact_keys(reason, keys), secrets=tuple(keys), limit=200)

    async def _release_key_safely(self, api_key: str) -> None:
        if self.reliability is None:
            return
        release_task = asyncio.create_task(self.reliability.release_key(api_key))
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError:
            await release_task
            raise

    def _safe_upstream_code(self, code: str | None) -> str | None:
        if not code:
            return None
        keys = self.reliability.raw_keys if self.reliability else ()
        value = sanitize_diagnostic_text(redact_keys(code, keys), secrets=tuple(keys), limit=80)
        value = "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in value)
        return value or None

    def _error(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        upstream_code: str | None = None,
    ) -> TavilyClientError:
        return TavilyClientError(
            message,
            code=code,
            retryable=retryable,
            http_status=http_status,
            upstream_code=upstream_code,
        )

    @staticmethod
    def _budget_error(
        budget: RequestBudget,
        *,
        code: str,
        message: str,
        termination_reason: str,
    ) -> TavilyClientError:
        return TavilyClientError(
            message,
            code=code,
            retryable=True,
            diagnostics={
                "termination_reason": termination_reason,
                "elapsed_ms": budget.elapsed_ms,
                "budget_ms": budget.budget_ms,
                "queue_wait_ms": budget.queue_wait_ms("tavily"),
            },
        )

    async def _reliability_error(
        self,
        code: str,
        message: str,
        *,
        service: dict[str, object],
        http_status: int | None = None,
        upstream_code: str | None = None,
    ) -> TavilyClientError:
        statuses = await self.reliability.status_summary() if self.reliability else []
        retryable = service.get("state") in {"open", "half_open"} or any(
            item.get("state") in {"healthy", "cooldown", "quota_exhausted"}
            for item in statuses
        )
        return TavilyClientError(
            message,
            code=code,
            key_statuses=statuses,
            service=service,
            retryable=retryable,
            http_status=http_status,
            upstream_code=upstream_code,
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
                retryable=True,
                http_status=response.status_code,
            )
        return data

    async def extract(self, url: str, *, budget: RequestBudget | None = None) -> str | None:
        data = await self._request(
            "/extract",
            {"urls": [url], "format": "markdown"},
            timeout=60.0,
            budget=budget,
        )
        results = data.get("results", [])
        if not results or not isinstance(results, list) or not isinstance(results[0], dict):
            return None
        content = results[0].get("raw_content", "")
        return content if isinstance(content, str) and content.strip() else None

    async def search(
        self,
        query: str,
        max_results: int = 6,
        *,
        budget: RequestBudget | None = None,
    ) -> list[TavilySearchResult]:
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
            budget=budget,
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
        budget: RequestBudget | None = None,
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
        data = await self._request(
            "/map",
            body,
            timeout=float(timeout + 10),
            budget=budget,
        )
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []
        results = [item.strip() for item in raw_results if isinstance(item, str) and item.strip()]
        return TavilyMapResult(
            base_url=(
                data.get("base_url", "") if isinstance(data.get("base_url", ""), str) else ""
            ),
            results=results,
            response_time=data.get("response_time", 0),
            ignored_results=len(raw_results) - len(results),
        )
