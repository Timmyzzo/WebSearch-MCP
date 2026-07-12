import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_base, wait_random_exponential

from ..config import config
from ..logger import log_info
from ..prompts import SEARCH_PROMPT

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def get_local_time_info() -> str:
    try:
        local_now = datetime.now().astimezone()
    except Exception:
        local_now = datetime.now(timezone.utc)

    weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return (
        "[Current Time Context]\n"
        f"- Date: {local_now.strftime('%Y-%m-%d')} ({weekdays_cn[local_now.weekday()]})\n"
        f"- Time: {local_now.strftime('%H:%M:%S')}\n"
        f"- Timezone: {local_now.tzname() or 'Local'}\n"
    )


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


class _WaitWithRetryAfter(wait_base):
    def __init__(self, multiplier: float, max_wait: int):
        self._base_wait = wait_random_exponential(multiplier=multiplier, max=max_wait)
        self._protocol_error_base = 3.0

    def __call__(self, retry_state: Any) -> float:
        if retry_state.outcome and retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = self._parse_retry_after(exc.response)
                if retry_after is not None:
                    return retry_after
            if isinstance(exc, httpx.RemoteProtocolError):
                return self._base_wait(retry_state) + self._protocol_error_base
        return self._base_wait(retry_state)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()
        if header.isdigit():
            return float(header)
        try:
            retry_dt = parsedate_to_datetime(header)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_dt - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


class GrokClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.transport = transport

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0, transport=self.transport) as client:
            response = await client.get(f"{self.api_url}/models", headers=self.headers)
            response.raise_for_status()
            data = response.json()
        return [
            item["id"]
            for item in (data or {}).get("data", []) or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    async def search(self, query: str, platform: str = "", ctx: Any = None) -> str:
        platform_prompt = ""
        if platform:
            platform_prompt = (
                "\n\nSearch the web for the information you need and focus on this platform: "
                f"{platform}\n"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SEARCH_PROMPT},
                {
                    "role": "user",
                    "content": get_local_time_info() + "\n" + query + platform_prompt,
                },
            ],
            "stream": True,
        }
        await log_info(ctx, f"platform_prompt: {query + platform_prompt}", config.debug_enabled)
        return await self._execute_stream_with_retry(payload, ctx)

    async def _parse_streaming_response(self, response: httpx.Response, ctx: Any = None) -> str:
        content = ""
        full_body_buffer: list[str] = []
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            full_body_buffer.append(line)
            if not line.startswith("data:") or line in ("data: [DONE]", "data:[DONE]"):
                continue
            try:
                data = json.loads(line[5:].lstrip())
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if isinstance(delta.get("content"), str):
                        content += delta["content"]
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        if not content and full_body_buffer:
            try:
                data = json.loads("".join(full_body_buffer))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
            except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
                pass

        await log_info(ctx, f"content: {content}", config.debug_enabled)
        return content

    async def _execute_stream_with_retry(self, payload: dict[str, Any], ctx: Any = None) -> str:
        timeout = httpx.Timeout(connect=6.0, read=120.0, write=10.0, pool=None)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(config.retry_max_attempts + 1),
                wait=_WaitWithRetryAfter(config.retry_multiplier, config.retry_max_wait),
                retry=retry_if_exception(_is_retryable_exception),
                reraise=True,
            ):
                with attempt:
                    async with client.stream(
                        "POST",
                        f"{self.api_url}/chat/completions",
                        headers=self.headers,
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        return await self._parse_streaming_response(response, ctx)
        return ""
