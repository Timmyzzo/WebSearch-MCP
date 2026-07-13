from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..budget import RequestBudget
from ..concurrency import AsyncConcurrencyLimiter, ConcurrencySlotTimeout
from ..config import config
from ..logger import log_info
from ..prompts import build_search_messages, current_time_context
from ..sources import merge_sources, split_answer_and_sources

_RELAY_ACCOUNT_PATTERNS = (
    "上游账号不可用",
    "上游账号异常",
    "死号",
    "账号池暂时不可用",
    "账号池不可用",
    "upstream account unavailable",
    "upstream account is unavailable",
    "no available upstream account",
    "account pool unavailable",
    "account pool temporarily unavailable",
    "dead account",
)
_MODEL_NOT_FOUND_PATTERNS = (
    "model_not_found",
    "model not found",
    "model does not exist",
    "unknown model",
    "模型不存在",
)
_MODEL_PERMISSION_PATTERNS = (
    "model_access_denied",
    "model_permission_denied",
    "permission denied for model",
    "does not have access to model",
    "not authorized to use model",
    "无权访问模型",
    "模型无权限",
)
_MODEL_UNAVAILABLE_PATTERNS = (
    "model_unavailable",
    "model temporarily unavailable",
    "model is unavailable",
    "model overloaded",
    "模型暂时不可用",
    "模型不可用",
)
_AUTH_PATTERNS = (
    "invalid_api_key",
    "authentication_error",
    "invalid authentication",
    "incorrect api key",
    "api key invalid",
    "api key is invalid",
    "认证失败",
    "密钥无效",
)

_SINGLE_ATTEMPT_READ_TIMEOUT = 120.0
_MIN_NEW_ATTEMPT_BUDGET = 1.0
_MAX_RESPONSES_SOURCES = 200


def get_local_time_info() -> str:
    context = current_time_context()
    return (
        "[Current Time Context]\n"
        f"- Date: {context['date']}\n"
        f"- Time: {context['time']}\n"
        f"- Timezone: {context['timezone']}\n"
    )


class _AttemptFailure(RuntimeError):
    def __init__(
        self,
        error_type: str,
        *,
        action: str,
        http_status: int | None = None,
        upstream_code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.action = action
        self.http_status = http_status
        self.upstream_code = upstream_code
        self.retry_after = retry_after


class GrokClientError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        primary_model: str,
        fallback_model: str | None,
        primary_attempts: int,
        fallback_attempts: int,
        last_failure: _AttemptFailure,
        switched_model: bool,
        termination_reason: str | None = None,
        configured_max_attempts: int | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.primary_attempts = primary_attempts
        self.fallback_attempts = fallback_attempts
        self.total_attempts = primary_attempts + fallback_attempts
        self.last_error_type = last_failure.error_type
        self.last_http_status = last_failure.http_status
        self.last_upstream_code = last_failure.upstream_code
        self.switched_model = switched_model
        self.termination_reason = termination_reason or (
            "non_retryable_error"
            if last_failure.action == "fatal"
            else "max_attempts_exhausted"
        )
        self.configured_max_attempts = configured_max_attempts or self.total_attempts
        self.actual_attempts = self.total_attempts
        self.elapsed_ms = budget.elapsed_ms if budget is not None else 0
        self.budget_ms = budget.budget_ms if budget is not None else 0
        self.queue_wait_ms = budget.queue_wait_ms("grok") if budget is not None else 0
        self.retryable = self.termination_reason in {
            "max_attempts_exhausted",
            "total_budget_exhausted",
            "concurrency_queue_timeout",
        } or last_failure.action in {"retry", "switch"}

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "service": "grok",
            "retryable": self.retryable,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "primary_attempts": self.primary_attempts,
            "fallback_attempts": self.fallback_attempts,
            "total_attempts": self.total_attempts,
            "last_error_type": self.last_error_type,
            "last_http_status": self.last_http_status,
            "last_upstream_code": self.last_upstream_code,
            "switched_model": self.switched_model,
            "termination_reason": self.termination_reason,
            "configured_max_attempts": self.configured_max_attempts,
            "actual_attempts": self.actual_attempts,
            "elapsed_ms": self.elapsed_ms,
            "budget_ms": self.budget_ms,
            "queue_wait_ms": self.queue_wait_ms,
            "diagnostics": {
                "termination_reason": self.termination_reason,
                "configured_max_attempts": self.configured_max_attempts,
                "actual_attempts": self.actual_attempts,
                "elapsed_ms": self.elapsed_ms,
                "budget_ms": self.budget_ms,
                "queue_wait_ms": self.queue_wait_ms,
                "last_error_type": self.last_error_type,
                "last_http_status": self.last_http_status,
                "last_upstream_code": self.last_upstream_code,
            },
        }


class GrokClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
        concurrency_limiter: AsyncConcurrencyLimiter | None = None,
        api_protocol: str | None = None,
        responses_max_tool_calls: int | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.transport = transport
        self._client = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()
        self._closed = False
        self._sleep = sleep
        self._random = random_source
        self.api_protocol = api_protocol
        self.responses_max_tool_calls = responses_max_tool_calls
        self._concurrency_limiter = concurrency_limiter or AsyncConcurrencyLimiter(
            config.grok_max_concurrency
        )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def __aenter__(self) -> GrokClient:
        await self._get_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("Grok HTTP 客户端已关闭")
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                timeout = httpx.Timeout(connect=6.0, read=120.0, write=10.0, pool=None)
                self._client = httpx.AsyncClient(
                    base_url=self.api_url,
                    timeout=timeout,
                    follow_redirects=True,
                    transport=self.transport,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
        return self._client

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def list_models(self) -> list[str]:
        response = await (await self._get_client()).get(
            "/models", headers=self.headers, timeout=10.0
        )
        if not response.is_success:
            await response.aread()
            raise self._classify_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Grok 模型列表返回了无效 JSON") from exc
        return [
            item["id"]
            for item in (data or {}).get("data", []) or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    async def search(
        self,
        query: str,
        platform: str = "",
        ctx: Any = None,
        *,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        max_attempts: int | None = None,
        supplemental_sources: list[dict[str, str]] | None = None,
        budget: RequestBudget | None = None,
    ) -> str:
        primary = primary_model or self.model
        _ = fallback_model  # Deprecated compatibility argument; single-model mode ignores it.
        if not primary:
            raise ValueError("Grok 主模型未配置")
        attempts_limit = (
            max_attempts if max_attempts is not None else config.grok_model_max_attempts
        )
        if attempts_limit < 1:
            raise ValueError("每个模型的最大尝试次数必须大于或等于 1")
        request_budget = budget or RequestBudget(config.web_search_total_timeout)
        api_protocol = self.api_protocol or config.grok_api_protocol
        responses_max_tool_calls = (
            self.responses_max_tool_calls
            if self.responses_max_tool_calls is not None
            else config.grok_responses_max_tool_calls
        )
        messages = build_search_messages(
            query,
            platform,
            supplemental_sources=supplemental_sources,
        )
        await log_info(ctx, "Prepared bounded search request", config.debug_enabled)

        counts = {primary: 0}
        last_failure = _AttemptFailure("upstream_unavailable", action="retry")
        for attempt_number in range(1, attempts_limit + 1):
            if request_budget.expired():
                last_failure = _AttemptFailure("total_budget_exhausted", action="retry")
                raise self._final_error(
                    primary,
                    counts,
                    last_failure,
                    termination_reason="total_budget_exhausted",
                    configured_max_attempts=attempts_limit,
                    budget=request_budget,
                )
            if (
                attempt_number > 1
                and request_budget.remaining() < _MIN_NEW_ATTEMPT_BUDGET
            ):
                last_failure = _AttemptFailure("total_budget_exhausted", action="retry")
                raise self._final_error(
                    primary,
                    counts,
                    last_failure,
                    termination_reason="total_budget_exhausted",
                    configured_max_attempts=attempts_limit,
                    budget=request_budget,
                )
            payload = self._build_search_payload(
                model=primary,
                messages=messages,
                api_protocol=api_protocol,
                responses_max_tool_calls=responses_max_tool_calls,
            )
            try:
                async with self._concurrency_limiter.slot(
                    request_budget,
                    service="grok",
                ):
                    remaining = request_budget.remaining()
                    if remaining <= 0:
                        raise _AttemptFailure(
                            "total_budget_exhausted",
                            action="retry",
                        )
                    counts[primary] += 1
                    try:
                        async with asyncio.timeout(remaining):
                            result = await self._execute_search_request(
                                payload,
                                api_protocol=api_protocol,
                                timeout=remaining,
                            )
                    except TimeoutError as exc:
                        raise _AttemptFailure(
                            "total_budget_exhausted",
                            action="retry",
                        ) from exc
                await log_info(
                    ctx,
                    f"Grok model {primary} completed via {api_protocol}",
                    config.debug_enabled,
                )
                return result
            except ConcurrencySlotTimeout as exc:
                last_failure = _AttemptFailure("concurrency_queue_timeout", action="retry")
                raise self._final_error(
                    primary,
                    counts,
                    last_failure,
                    termination_reason="concurrency_queue_timeout",
                    configured_max_attempts=attempts_limit,
                    budget=request_budget,
                ) from exc
            except _AttemptFailure as exc:
                last_failure = exc
                if exc.action == "fatal":
                    raise self._final_error(
                        primary,
                        counts,
                        exc,
                        termination_reason="non_retryable_error",
                        configured_max_attempts=attempts_limit,
                        budget=request_budget,
                    ) from exc
                if exc.error_type == "total_budget_exhausted":
                    raise self._final_error(
                        primary,
                        counts,
                        exc,
                        termination_reason="total_budget_exhausted",
                        configured_max_attempts=attempts_limit,
                        budget=request_budget,
                    ) from exc
                if attempt_number >= attempts_limit:
                    break
                delay = self._retry_delay(attempt_number, exc.retry_after)
                if request_budget.remaining() < delay + _MIN_NEW_ATTEMPT_BUDGET:
                    raise self._final_error(
                        primary,
                        counts,
                        exc,
                        termination_reason="total_budget_exhausted",
                        configured_max_attempts=attempts_limit,
                        budget=request_budget,
                    ) from exc
                try:
                    async with asyncio.timeout(request_budget.remaining()):
                        await self._sleep(delay)
                except TimeoutError as timeout_exc:
                    raise self._final_error(
                        primary,
                        counts,
                        exc,
                        termination_reason="total_budget_exhausted",
                        configured_max_attempts=attempts_limit,
                        budget=request_budget,
                    ) from timeout_exc
            except Exception as exc:
                last_failure = _AttemptFailure("client_error", action="fatal")
                raise self._final_error(
                    primary,
                    counts,
                    last_failure,
                    termination_reason="non_retryable_error",
                    configured_max_attempts=attempts_limit,
                    budget=request_budget,
                ) from exc

        raise self._final_error(
            primary,
            counts,
            last_failure,
            termination_reason="max_attempts_exhausted",
            configured_max_attempts=attempts_limit,
            budget=request_budget,
        )

    def _final_error(
        self,
        primary: str,
        counts: dict[str, int],
        failure: _AttemptFailure,
        *,
        termination_reason: str,
        configured_max_attempts: int,
        budget: RequestBudget,
    ) -> GrokClientError:
        if termination_reason == "concurrency_queue_timeout":
            code = "grok_concurrency_timeout"
            message = "Grok 模型调用失败，等待上游并发槽位时预算耗尽"
        elif termination_reason == "total_budget_exhausted":
            code = "grok_total_budget_exhausted"
            message = "Grok 模型调用失败，搜索总时间预算已耗尽"
        elif failure.error_type == "authentication_error":
            code = "grok_authentication_error"
            message = "Grok API 认证失败，请检查 GROK_API_KEY；因不可重试错误提前停止"
        elif failure.error_type == "request_invalid":
            code = "grok_request_invalid"
            message = "Grok 请求参数无效，因不可重试错误提前停止"
        elif termination_reason == "non_retryable_error":
            code = "grok_primary_failed"
            message = "Grok 模型调用失败，因不可重试错误提前停止"
        else:
            code = "grok_primary_failed"
            message = "Grok 模型调用失败，已用尽最大尝试次数"
        return GrokClientError(
            code=code,
            message=message,
            primary_model=primary,
            fallback_model=None,
            primary_attempts=counts.get(primary, 0),
            fallback_attempts=0,
            last_failure=failure,
            switched_model=False,
            termination_reason=termination_reason,
            configured_max_attempts=configured_max_attempts,
            budget=budget,
        )

    def _retry_delay(self, attempt_number: int, retry_after: float | None) -> float:
        base = min(
            float(config.retry_max_wait),
            float(config.retry_multiplier) * (2 ** (attempt_number - 1)),
        )
        delay = base * (0.5 + 0.5 * min(1.0, max(0.0, self._random())))
        return max(delay, retry_after or 0.0)

    def _build_search_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        api_protocol: str,
        responses_max_tool_calls: int,
    ) -> dict[str, Any]:
        if api_protocol == "chat_completions":
            return {"model": model, "messages": messages, "stream": True}
        if api_protocol != "responses":
            raise ValueError(f"不支持的 Grok API 协议: {api_protocol}")

        if "openrouter" in self.api_url.casefold():
            tool: dict[str, Any] = {
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": "auto",
                    "max_results": 5,
                    "max_total_results": min(20, responses_max_tool_calls),
                },
            }
        else:
            tool = {"type": "web_search"}

        return {
            "model": model,
            "input": messages,
            "tools": [tool],
            "max_tool_calls": responses_max_tool_calls,
            "parallel_tool_calls": True,
            "store": False,
            "stream": False,
        }

    async def _execute_search_request(
        self,
        payload: dict[str, Any],
        *,
        api_protocol: str,
        timeout: float,
    ) -> str:
        if api_protocol == "responses":
            return await self._execute_responses(payload, timeout=timeout)
        return await self._execute_stream(payload, timeout=timeout)

    async def _execute_responses(self, payload: dict[str, Any], *, timeout: float) -> str:
        try:
            response = await (await self._get_client()).post(
                "/responses",
                headers=self.headers,
                json=payload,
                timeout=httpx.Timeout(
                    connect=min(6.0, timeout),
                    read=min(_SINGLE_ATTEMPT_READ_TIMEOUT, timeout),
                    write=min(10.0, timeout),
                    pool=timeout,
                ),
            )
            if not response.is_success:
                await response.aread()
                raise self._classify_response(response)
            try:
                data = response.json()
            except ValueError as exc:
                raise _AttemptFailure("invalid_response", action="retry") from exc
            return self._parse_responses_response(data, response.status_code)
        except _AttemptFailure:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            raise _AttemptFailure("connection_failure", action="retry") from exc
        except httpx.ReadTimeout as exc:
            raise _AttemptFailure("read_timeout", action="retry") from exc
        except httpx.TimeoutException as exc:
            raise _AttemptFailure("timeout", action="retry") from exc
        except (httpx.RemoteProtocolError, httpx.NetworkError, httpx.RequestError) as exc:
            raise _AttemptFailure("network_failure", action="retry") from exc

    def _parse_responses_response(self, data: object, status_code: int = 200) -> str:
        if not isinstance(data, dict):
            raise _AttemptFailure("invalid_response", action="retry")
        if isinstance(data.get("error"), dict):
            raise self._classify_error_data(data, status_code)

        response_status = data.get("status")
        if isinstance(response_status, str) and response_status != "completed":
            error_type = (
                "response_incomplete"
                if response_status in {"incomplete", "in_progress"}
                else "invalid_response"
            )
            raise _AttemptFailure(error_type, action="retry")

        text = self._responses_text(data)
        if not text.strip():
            raise _AttemptFailure("empty_response", action="retry")

        answer, embedded_sources = split_answer_and_sources(text)
        response_sources = self._responses_sources(data)
        sources = merge_sources(embedded_sources, response_sources)
        if not sources:
            return text

        return (
            answer.rstrip()
            + "\n\nsources("
            + json.dumps(sources, ensure_ascii=False, separators=(",", ":"))
            + ")"
        )

    @staticmethod
    def _responses_text(data: dict[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        texts: list[str] = []
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type and item_type != "message" and not isinstance(
                    item.get("message"), dict
                ):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    message = item.get("message")
                    content = message.get("content") if isinstance(message, dict) else content
                if isinstance(content, str) and content.strip():
                    texts.append(content.strip())
                    continue
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, str) and block.strip():
                        texts.append(block.strip())
                    elif isinstance(block, dict):
                        value = block.get("text") or block.get("content")
                        if isinstance(value, str) and value.strip():
                            texts.append(value.strip())

        if not texts:
            choices = data.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    message = choice.get("message")
                    value = (
                        message.get("content")
                        if isinstance(message, dict)
                        else choice.get("text")
                    )
                    if isinstance(value, str) and value.strip():
                        texts.append(value.strip())
        return "\n\n".join(texts).strip()

    def _responses_sources(self, data: dict[str, Any]) -> list[dict[str, str]]:
        candidates: list[object] = []
        self._collect_annotations(data, candidates)

        citations = data.get("citations")
        if isinstance(citations, list):
            candidates.extend(citations)

        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or "search" not in str(item.get("type", "")):
                    continue
                action = item.get("action")
                if isinstance(action, dict):
                    for key in ("sources", "results", "search_results", "web_results"):
                        values = action.get(key)
                        if isinstance(values, list):
                            candidates.extend(values)
                    if action.get("url"):
                        candidates.append(action)
                for key in ("sources", "results", "search_results"):
                    values = item.get(key)
                    if isinstance(values, list):
                        candidates.extend(values)

        sources: list[dict[str, str]] = []
        for candidate in candidates:
            source = self._response_source(candidate)
            if source is not None:
                sources.append(source)
            if len(sources) >= _MAX_RESPONSES_SOURCES:
                break
        return merge_sources(sources)

    @classmethod
    def _collect_annotations(cls, value: object, out: list[object]) -> None:
        if isinstance(value, list):
            for item in value:
                cls._collect_annotations(item, out)
            return
        if not isinstance(value, dict):
            return
        annotations = value.get("annotations")
        if isinstance(annotations, list):
            out.extend(annotations)
        for key, nested in value.items():
            if key != "annotations" and isinstance(nested, (dict, list)):
                cls._collect_annotations(nested, out)

    @staticmethod
    def _response_source(value: object) -> dict[str, str] | None:
        if isinstance(value, str):
            url = value.strip()
            title = ""
            description = ""
        elif isinstance(value, dict):
            nested_source = value.get("source")
            nested_citation = value.get("citation") or value.get("url_citation")
            nested = nested_source if isinstance(nested_source, dict) else nested_citation
            url = next(
                (
                    item.strip()
                    for item in (
                        value.get("url"),
                        value.get("href"),
                        value.get("link"),
                        value.get("uri"),
                        nested.get("url") if isinstance(nested, dict) else None,
                    )
                    if isinstance(item, str) and item.strip()
                ),
                "",
            )
            title = next(
                (
                    item.strip()
                    for item in (
                        value.get("title"),
                        value.get("name"),
                        value.get("label"),
                        nested.get("title") if isinstance(nested, dict) else None,
                    )
                    if isinstance(item, str) and item.strip()
                ),
                "",
            )
            description = next(
                (
                    item.strip()
                    for item in (
                        value.get("snippet"),
                        value.get("description"),
                        value.get("summary"),
                        nested.get("snippet") if isinstance(nested, dict) else None,
                    )
                    if isinstance(item, str) and item.strip()
                ),
                "",
            )
        else:
            return None

        if not url.startswith(("http://", "https://")):
            return None
        source = {"url": url, "provider": "grok-responses"}
        if title:
            source["title"] = title
        if description:
            source["description"] = description
        return source

    async def _execute_stream(self, payload: dict[str, Any], *, timeout: float) -> str:
        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                "/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=httpx.Timeout(
                    connect=min(6.0, timeout),
                    read=min(_SINGLE_ATTEMPT_READ_TIMEOUT, timeout),
                    write=min(10.0, timeout),
                    pool=timeout,
                ),
            ) as response:
                if not response.is_success:
                    await response.aread()
                    raise self._classify_response(response)
                return await self._parse_streaming_response(response)
        except _AttemptFailure:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            raise _AttemptFailure("connection_failure", action="retry") from exc
        except httpx.ReadTimeout as exc:
            raise _AttemptFailure("read_timeout", action="retry") from exc
        except httpx.TimeoutException as exc:
            raise _AttemptFailure("timeout", action="retry") from exc
        except (httpx.RemoteProtocolError, httpx.NetworkError, httpx.RequestError) as exc:
            raise _AttemptFailure("network_failure", action="retry") from exc

    async def _parse_streaming_response(self, response: httpx.Response) -> str:
        content: list[str] = []
        body_lines: list[str] = []
        saw_sse = False
        completed = False
        try:
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line:
                    continue
                body_lines.append(line)
                if not line.startswith("data:"):
                    continue
                saw_sse = True
                payload_text = line[5:].lstrip()
                if payload_text == "[DONE]":
                    completed = True
                    continue
                try:
                    data = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and isinstance(data.get("error"), dict):
                    raise self._classify_error_data(data, response.status_code)
                choices = data.get("choices", []) if isinstance(data, dict) else []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    content.append(delta["content"])
                if choice.get("finish_reason") is not None:
                    completed = True
        except _AttemptFailure:
            raise
        except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as exc:
            result = "".join(content)
            if completed and result.strip():
                return result
            error_type = "stream_interrupted_after_content" if content else "stream_interrupted"
            raise _AttemptFailure(error_type, action="retry") from exc

        if saw_sse:
            if not completed:
                error_type = "stream_interrupted_after_content" if content else "stream_interrupted"
                raise _AttemptFailure(error_type, action="retry")
            result = "".join(content)
            if result.strip():
                return result
            raise _AttemptFailure("empty_response", action="retry")

        raw_body = "\n".join(body_lines)
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise _AttemptFailure("invalid_response", action="retry") from exc
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            raise self._classify_error_data(data, response.status_code)
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            result = message.get("content", "") if isinstance(message, dict) else ""
            if isinstance(result, str) and result.strip():
                return result
        raise _AttemptFailure("empty_response", action="retry")

    def _classify_response(self, response: httpx.Response) -> _AttemptFailure:
        try:
            data = response.json()
        except ValueError:
            data = None
        return self._classify_error_data(data, response.status_code, response.headers)

    def _classify_error_data(
        self,
        data: object,
        status: int,
        headers: httpx.Headers | None = None,
    ) -> _AttemptFailure:
        code, error_type, message = self._error_fields(data)
        combined = " ".join(part for part in (code, error_type, message) if part).lower()
        upstream_code = self._safe_upstream_code(code or error_type)

        if self._matches(combined, _RELAY_ACCOUNT_PATTERNS):
            return _AttemptFailure(
                "relay_upstream_account_unavailable",
                action="retry",
                http_status=status,
                upstream_code=upstream_code,
                retry_after=self._parse_retry_after(headers),
            )
        if self._matches(combined, _MODEL_NOT_FOUND_PATTERNS):
            return _AttemptFailure(
                "model_not_found",
                action="fatal",
                http_status=status,
                upstream_code=upstream_code,
            )
        if self._matches(combined, _MODEL_PERMISSION_PATTERNS):
            return _AttemptFailure(
                "model_permission_denied",
                action="fatal",
                http_status=status,
                upstream_code=upstream_code,
            )
        if self._matches(combined, _MODEL_UNAVAILABLE_PATTERNS):
            return _AttemptFailure(
                "model_unavailable",
                action="retry",
                http_status=status,
                upstream_code=upstream_code,
            )
        if status in {401, 403} or self._matches(combined, _AUTH_PATTERNS):
            return _AttemptFailure(
                "authentication_error",
                action="fatal",
                http_status=status,
                upstream_code=upstream_code,
            )
        if status in {400, 422}:
            return _AttemptFailure(
                "request_invalid",
                action="fatal",
                http_status=status,
                upstream_code=upstream_code,
            )
        if status == 408 or status == 429 or 500 <= status < 600:
            return _AttemptFailure(
                "upstream_unavailable" if status != 429 else "rate_limited",
                action="retry",
                http_status=status,
                upstream_code=upstream_code,
                retry_after=self._parse_retry_after(headers),
            )
        return _AttemptFailure(
            "upstream_rejected",
            action="fatal",
            http_status=status,
            upstream_code=upstream_code,
        )

    @staticmethod
    def _error_fields(data: object) -> tuple[str, str, str]:
        if not isinstance(data, dict):
            return "", "", ""
        error = data.get("error", data)
        if not isinstance(error, dict):
            return "", "", str(error) if isinstance(error, str) else ""
        return tuple(
            value if isinstance(value, str) else ""
            for value in (error.get("code"), error.get("type"), error.get("message"))
        )

    @staticmethod
    def _matches(text: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in text for pattern in patterns)

    def _safe_upstream_code(self, value: str) -> str | None:
        if not value:
            return None
        value = value.replace(self.api_key, "[REDACTED]")
        value = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"[^a-zA-Z0-9_.:-]", "_", value)[:80]
        return value or None

    @staticmethod
    def _parse_retry_after(headers: httpx.Headers | None) -> float | None:
        if headers is None:
            return None
        header = headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
        try:
            retry_dt = parsedate_to_datetime(header)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_dt - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None
