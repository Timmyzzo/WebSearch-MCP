import json

import httpx

from grok_search.clients.tavily import TavilyClient


async def test_tavily_search_extract_and_map_use_expected_endpoints():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (request.url.path, request.headers["authorization"], json.loads(request.content))
        )
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Docs",
                            "url": "https://example.com/docs",
                            "content": "Text",
                            "score": 0.9,
                        }
                    ]
                },
            )
        if request.url.path == "/extract":
            return httpx.Response(200, json={"results": [{"raw_content": "# Page"}]})
        return httpx.Response(
            200,
            json={
                "base_url": "https://example.com",
                "results": ["https://example.com/docs"],
                "response_time": 0.2,
            },
        )

    keys = iter(["key-one", "key-two", "key-three"])
    client = TavilyClient(
        "https://api.tavily.com/",
        lambda: next(keys),
        transport=httpx.MockTransport(handler),
    )

    search = await client.search("query", 3)
    extract = await client.extract("https://example.com/docs")
    site_map = await client.map("https://example.com", instructions="docs only")

    assert search[0].url == "https://example.com/docs"
    assert extract == "# Page"
    assert site_map.results == ["https://example.com/docs"]
    assert [item[0] for item in requests] == ["/search", "/extract", "/map"]
    assert [item[1] for item in requests] == [
        "Bearer key-one",
        "Bearer key-two",
        "Bearer key-three",
    ]
    assert requests[2][2]["instructions"] == "docs only"
