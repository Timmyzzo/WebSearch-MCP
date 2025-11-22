from fastmcp import FastMCP, Context
from .providers.grok import GrokSearchProvider
from .utils import format_search_results
from .logger import log_info
from .config import config
import asyncio

mcp = FastMCP("grok-search")

@mcp.tool(
    name="web_search",
    description="""
    Performs a third-party web search based on the given query and returns the results
    as a JSON string.

    The `query` should be a clear, self-contained natural-language search query.
    When helpful, include constraints such as topic, time range, language, or domain.

    The `platform` should be the platforms which you should focus on searching, such as "Twitter", "GitHub", "Reddit", etc.

    The `min_results` and `max_results` should be the minimum and maximum number of results to return.

    Returns
    -------
    str
        A JSON-encoded string representing a list of search results. Each result
        includes at least:
        - `url`: the link to the result
        - `title`: a short title
        - `summary`: a brief description or snippet of the page content.
    """,
    meta={"author": "GuDa"}
)
async def web_search(query: str, platform: str = "", min_results: int = 3, max_results: int = 10, ctx: Context = None) -> str:
    try:
        api_url = config.grok_api_url
        api_key = config.grok_api_key
    except ValueError as e:
        error_msg = str(e)
        if ctx:
            await ctx.report_progress(error_msg)
        return f"配置错误: {error_msg}"
    
    grok_provider = GrokSearchProvider(api_url, api_key)
    
    await log_info(ctx, f"Begin Search: {query}", config.debug_enabled)
    results = await grok_provider.search(query, platform, min_results, max_results, ctx)
    await log_info(ctx, "Search Finished!", config.debug_enabled)
    return results





def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
