from collections.abc import Callable
from typing import Any

import httpx

from ..models import TavilyMapResult, TavilySearchResult


class TavilyClientError(RuntimeError):
    pass


class TavilyClient:
    def __init__(
        self,
        api_url: str,
        key_provider: Callable[[], str | None],
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.key_provider = key_provider
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        api_key = self.key_provider()
        if not api_key:
            raise TavilyClientError(
                "配置错误: TAVILY_API_KEY 未配置，请设置 TAVILY_API_KEY 或 TAVILY_API_KEYS"
            )
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def extract(self, url: str) -> str | None:
        body = {"urls": [url], "format": "markdown"}
        try:
            async with httpx.AsyncClient(timeout=60.0, transport=self.transport) as client:
                response = await client.post(
                    f"{self.api_url}/extract",
                    headers=self._headers(),
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except TavilyClientError:
            raise
        except Exception:
            return None

        results = data.get("results", [])
        if not results:
            return None
        content = results[0].get("raw_content", "")
        return content if isinstance(content, str) and content.strip() else None

    async def search(self, query: str, max_results: int = 6) -> list[TavilySearchResult]:
        body = {
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_raw_content": False,
            "include_answer": False,
        }
        try:
            async with httpx.AsyncClient(timeout=90.0, transport=self.transport) as client:
                response = await client.post(
                    f"{self.api_url}/search",
                    headers=self._headers(),
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except TavilyClientError:
            raise
        except Exception:
            return []

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

        try:
            async with httpx.AsyncClient(
                timeout=float(timeout + 10),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.api_url}/map",
                    headers=self._headers(),
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except TavilyClientError:
            raise
        except httpx.TimeoutException as exc:
            raise TavilyClientError(f"映射超时: 请求超过{timeout}秒") from exc
        except httpx.HTTPStatusError as exc:
            raise TavilyClientError(
                f"HTTP错误: {exc.response.status_code} - {exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise TavilyClientError(f"映射错误: {exc}") from exc

        return TavilyMapResult(
            base_url=data.get("base_url", ""),
            results=data.get("results", []),
            response_time=data.get("response_time", 0),
        )
